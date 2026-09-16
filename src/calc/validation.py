"""Валидация замеров АГЗУ (well_test). Первый расчётный модуль — раньше это
делалось глазами в Excel.

Каждое правило — независимая чистая функция rule(test, context) ->
ValidationResult, без обращения к БД (тестируется без сессии/фикстур).
Сборку RuleContext из БД делает src/calc/validation_runner.py.

Все пороги — в config/validation_rules.yaml, резолвятся через resolve_config()
(default -> поле -> скважина). В коде порогов нет.
"""

from __future__ import annotations

import datetime as dt
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Callable

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "validation_rules.yaml"


# --- конфигурация -----------------------------------------------------------


def load_raw_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_config(
    raw_config: dict,
    field_id: int | None = None,
    well_id: int | None = None,
    node_type: str | None = None,
) -> dict:
    """default -> overrides.field[field_id] -> overrides.well[well_id], каждый
    уровень мержится точечно. node_type применяется последним и трогает только
    duration_check.min_hours (см. by_node_type в конфиге)."""

    cfg = deepcopy(raw_config["default"])
    overrides = raw_config.get("overrides", {})

    field_override = overrides.get("field", {}).get(str(field_id)) if field_id is not None else None
    if field_override:
        cfg = _deep_merge(cfg, field_override)

    well_override = overrides.get("well", {}).get(str(well_id)) if well_id is not None else None
    if well_override:
        cfg = _deep_merge(cfg, well_override)

    if node_type is not None:
        by_type = cfg.get("duration_check", {}).get("by_node_type", {})
        if node_type in by_type:
            cfg["duration_check"]["min_hours"] = by_type[node_type]

    return cfg


# --- модель результата -------------------------------------------------------


@dataclass
class ValidationResult:
    rule: str
    passed: bool
    severity: str  # "error" | "warning" — значим только при passed=False
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class EventInfo:
    """Событие, объясняющее резкое изменение показателей скважины."""

    kind: str  # "gtm" | "pump_change" | "downtime_end"
    at: dt.datetime
    description: str


@dataclass
class RuleContext:
    config: dict
    previous_valid_test: object | None = None  # WellTest | None
    events: list[EventInfo] = field(default_factory=list)
    gor_history: list[float] = field(default_factory=list)
    sibling_tests: list[object] = field(default_factory=list)  # другие скважины того же узла, та же дата
    node_fact: dict | None = None  # {"q_liquid_t": ..., "q_oil_t": ...}
    telemetry_current: list[float] | None = None  # ток ЭЦН (А) за окно замера


def _has_explaining_event(context: RuleContext, test, window_days: int) -> EventInfo | None:
    window = dt.timedelta(days=window_days)
    for ev in context.events:
        if abs(ev.at - test.ts_start) <= window:
            return ev
    return None


# --- правила ------------------------------------------------------------------


def duration_check(test, context: RuleContext) -> ValidationResult:
    min_hours = context.config["duration_check"]["min_hours"]
    passed = test.duration_h >= min_hours
    return ValidationResult(
        rule="duration_check",
        passed=passed,
        severity="error",
        message=f"длительность замера {test.duration_h:.2f} ч < норматива {min_hours} ч" if not passed else "ok",
        details={"duration_h": test.duration_h, "min_hours": min_hours},
    )


def physical_bounds(test, context: RuleContext) -> ValidationResult:
    bounds = context.config["physical_bounds"]
    violations: dict[str, dict] = {}

    def _check(name: str, value: float | None, bound_key: str) -> None:
        if value is None:
            return
        b = bounds[bound_key]
        if not (b["min"] <= value <= b["max"]):
            violations[name] = {"value": value, "min": b["min"], "max": b["max"]}

    _check("water_cut", test.water_cut, "water_cut_pct")
    _check("gor", test.gor, "gor_m3_t")
    _check("p_buf", test.p_buf, "p_buf_atm")
    _check("p_zatr", test.p_zatr, "p_zatr_atm")
    _check("q_liquid", test.q_liquid, "q_liquid_t_d")
    _check("q_oil", test.q_oil, "q_oil_t_d")
    _check("q_water", test.q_water, "q_water_t_d")
    _check("q_gas", test.q_gas, "q_gas_m3_d")

    passed = not violations
    return ValidationResult(
        rule="physical_bounds",
        passed=passed,
        severity="error",
        message=f"вне физических пределов: {', '.join(violations)}" if not passed else "ok",
        details={"violations": violations},
    )


def deviation_from_previous(test, context: RuleContext) -> ValidationResult:
    cfg = context.config["deviation_from_previous"]
    prev = context.previous_valid_test

    if prev is None or not prev.q_liquid:
        return ValidationResult(
            rule="deviation_from_previous",
            passed=True,
            severity="warning",
            message="нет предыдущего валидного замера для сравнения",
            details={},
        )

    pct_change = abs(test.q_liquid - prev.q_liquid) / prev.q_liquid * 100
    within_threshold = pct_change <= cfg["max_change_pct"]

    if within_threshold:
        return ValidationResult(
            rule="deviation_from_previous",
            passed=True,
            severity="warning",
            message="ok",
            details={"pct_change": round(pct_change, 1)},
        )

    event = _has_explaining_event(context, test, cfg["event_window_days"])
    if event is not None:
        return ValidationResult(
            rule="deviation_from_previous",
            passed=True,
            severity="warning",
            message=f"отклонение {pct_change:.1f}% объяснено событием: {event.description}",
            details={"pct_change": round(pct_change, 1), "explained_by": event.kind},
        )

    return ValidationResult(
        rule="deviation_from_previous",
        passed=False,
        severity="warning",
        message=f"Qж изменился на {pct_change:.1f}% без объясняющего события в окне ±{cfg['event_window_days']} сут",
        details={"pct_change": round(pct_change, 1), "prev_q_liquid": prev.q_liquid, "q_liquid": test.q_liquid},
    )


def water_cut_jump(test, context: RuleContext) -> ValidationResult:
    cfg = context.config["water_cut_jump"]
    prev = context.previous_valid_test

    if prev is None or prev.water_cut is None or test.water_cut is None:
        return ValidationResult(
            rule="water_cut_jump", passed=True, severity="warning", message="нет данных для сравнения", details={}
        )

    jump_pp = abs(test.water_cut - prev.water_cut)
    if jump_pp <= cfg["max_jump_pp"]:
        return ValidationResult(
            rule="water_cut_jump", passed=True, severity="warning", message="ok", details={"jump_pp": round(jump_pp, 1)}
        )

    event = _has_explaining_event(context, test, cfg["event_window_days"])
    if event is not None:
        return ValidationResult(
            rule="water_cut_jump",
            passed=True,
            severity="warning",
            message=f"скачок обводнённости {jump_pp:.1f} п.п. объяснён событием: {event.description}",
            details={"jump_pp": round(jump_pp, 1), "explained_by": event.kind},
        )

    return ValidationResult(
        rule="water_cut_jump",
        passed=False,
        severity="warning",
        message=f"обводнённость скакнула на {jump_pp:.1f} п.п. без объясняющего события",
        details={"jump_pp": round(jump_pp, 1), "prev_water_cut": prev.water_cut, "water_cut": test.water_cut},
    )


def gor_anomaly(test, context: RuleContext) -> ValidationResult:
    cfg = context.config["gor_anomaly"]

    if test.gor is None or len(context.gor_history) < 2:
        return ValidationResult(
            rule="gor_anomaly",
            passed=True,
            severity="warning",
            message="недостаточно истории ГФ для сравнения",
            details={"history_len": len(context.gor_history)},
        )

    rolling_avg = mean(context.gor_history)
    if rolling_avg == 0:
        return ValidationResult(
            rule="gor_anomaly", passed=True, severity="warning", message="среднее ГФ равно нулю, пропуск", details={}
        )

    pct_dev = abs(test.gor - rolling_avg) / rolling_avg * 100
    passed = pct_dev <= cfg["max_deviation_pct"]
    return ValidationResult(
        rule="gor_anomaly",
        passed=passed,
        severity="warning",
        message=f"ГФ {test.gor:.1f} отклоняется от скользящего среднего {rolling_avg:.1f} на {pct_dev:.1f}%"
        if not passed
        else "ok",
        details={"gor": test.gor, "rolling_avg": round(rolling_avg, 1), "pct_dev": round(pct_dev, 1)},
    )


def material_balance(test, context: RuleContext) -> ValidationResult:
    cfg = context.config["material_balance"]
    tolerance = cfg["tolerance_pct"]

    if context.node_fact is None:
        return ValidationResult(
            rule="material_balance", passed=True, severity="warning", message="нет факта по узлу за эту дату", details={}
        )

    def _discrepancy(metric: str) -> dict | None:
        fact = context.node_fact.get(metric)
        if fact is None or fact == 0:
            return None
        wells_sum = test.__getattribute__("q_liquid" if metric == "q_liquid_t" else "q_oil")
        wells_sum += sum(
            (s.q_liquid if metric == "q_liquid_t" else s.q_oil) for s in context.sibling_tests
        )
        pct = abs(wells_sum - fact) / fact * 100
        return {"sum_wells": round(wells_sum, 2), "node_fact": fact, "discrepancy_pct": round(pct, 1)}

    liquid = _discrepancy("q_liquid_t")
    oil = _discrepancy("q_oil_t")

    failing = [
        name
        for name, d in (("liquid", liquid), ("oil", oil))
        if d is not None and d["discrepancy_pct"] > tolerance
    ]
    passed = not failing

    return ValidationResult(
        rule="material_balance",
        passed=passed,
        severity="warning",
        message=f"расхождение узла/скважин превышает {tolerance}%: {', '.join(failing)}" if not passed else "ok",
        details={"liquid": liquid, "oil": oil, "tolerance_pct": tolerance},
    )


def staleness(test, context: RuleContext) -> ValidationResult:
    cfg = context.config["staleness"]
    prev = context.previous_valid_test

    if prev is None:
        return ValidationResult(
            rule="staleness", passed=True, severity="warning", message="нет предыдущего валидного замера", details={}
        )

    gap_days = (test.ts_start - prev.ts_end).total_seconds() / 86400
    passed = gap_days <= cfg["max_days_since_last_valid"]
    return ValidationResult(
        rule="staleness",
        passed=passed,
        severity="warning",
        message=f"с последнего валидного замера прошло {gap_days:.1f} сут (> {cfg['max_days_since_last_valid']})"
        if not passed
        else "ok",
        details={"gap_days": round(gap_days, 1), "max_days": cfg["max_days_since_last_valid"]},
    )


def telemetry_consistency(test, context: RuleContext) -> ValidationResult:
    cfg = context.config["telemetry_consistency"]

    if not context.telemetry_current:
        return ValidationResult(
            rule="telemetry_consistency",
            passed=True,
            severity="error",
            message="нет данных телеметрии тока за окно замера — нечем проверить",
            details={"telemetry_available": False},
        )

    if test.q_liquid is None or test.q_liquid < cfg["min_flow_to_expect_current_t_d"]:
        return ValidationResult(
            rule="telemetry_consistency",
            passed=True,
            severity="error",
            message="дебит слишком мал, чтобы ожидать ток ЭЦН",
            details={},
        )

    avg_current = mean(context.telemetry_current)
    passed = avg_current >= cfg["min_current_a"]
    return ValidationResult(
        rule="telemetry_consistency",
        passed=passed,
        severity="error",
        message=f"замер заявляет Qж={test.q_liquid:.1f} т/сут, но средний ток ЭЦН {avg_current:.1f} А "
        f"< {cfg['min_current_a']} А — насос, похоже, не работал"
        if not passed
        else "ok",
        details={"avg_current_a": round(avg_current, 1), "min_current_a": cfg["min_current_a"]},
    )


RULES: dict[str, Callable[[object, RuleContext], ValidationResult]] = {
    "duration_check": duration_check,
    "physical_bounds": physical_bounds,
    "deviation_from_previous": deviation_from_previous,
    "water_cut_jump": water_cut_jump,
    "gor_anomaly": gor_anomaly,
    "material_balance": material_balance,
    "staleness": staleness,
    "telemetry_consistency": telemetry_consistency,
}


@dataclass
class RunResult:
    is_valid: bool
    validation_flags: dict
    results: list[ValidationResult]


def evaluate(test, context: RuleContext, rules: dict[str, Callable] = RULES) -> RunResult:
    """Прогоняет все правила и собирает итоговые is_valid/validation_flags.

    is_valid = False, только если провалилось хотя бы одно error-правило —
    warning-правила используются "с осторожностью", но не бракуют замер.
    """
    results = [rule_fn(test, context) for rule_fn in rules.values()]

    errors = [r.rule for r in results if not r.passed and r.severity == "error"]
    warnings = [r.rule for r in results if not r.passed and r.severity == "warning"]
    details = {r.rule: {"message": r.message, **r.details} for r in results if not r.passed}

    return RunResult(
        is_valid=len(errors) == 0,
        validation_flags={"errors": errors, "warnings": warnings, "details": details},
        results=results,
    )
