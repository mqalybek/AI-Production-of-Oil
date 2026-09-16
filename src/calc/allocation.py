"""Back-allocation: распределение факта добычи узла по скважинам.

Чистая математика — без обращения к БД (тестируется без сессии). Сборку
входных данных из БД и запись в daily_production делает
src/calc/allocation_runner.py.

Ключевые решения (согласованы с автором, см. ADR в CLAUDE.md):
- аллокация ведётся по 4 фазам независимо (нефть/жидкость/вода/газ), у
  каждой свой K и своя проверка границ;
- K вне [0.7, 1.3] всё равно применяется (иначе не сходится инвариант
  суммы), но помечается предупреждением — не блокируется;
- экстраполяция устаревшего замера — простая экспоненциальная по
  последним N валидным замерам (без полноценного DCA);
- аналог для новой скважины — медиана свежих валидных замеров скважин
  того же объекта разработки (completion.reservoir_id).
"""

from __future__ import annotations

import datetime as dt
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "allocation_rules.yaml"

PHASES = ("oil", "liquid", "water", "gas")
_TEST_ATTR = {"oil": "q_oil", "liquid": "q_liquid", "water": "q_water", "gas": "q_gas"}


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


def resolve_config(raw_config: dict, field_id: int | None = None, well_id: int | None = None) -> dict:
    cfg = deepcopy(raw_config["default"])
    overrides = raw_config.get("overrides", {})

    field_override = overrides.get("field", {}).get(str(field_id)) if field_id is not None else None
    if field_override:
        cfg = _deep_merge(cfg, field_override)

    well_override = overrides.get("well", {}).get(str(well_id)) if well_id is not None else None
    if well_override:
        cfg = _deep_merge(cfg, well_override)

    return cfg


# --- модель данных ------------------------------------------------------------


@dataclass
class TestPoint:
    """Один валидный замер, минимум полей, нужных для аллокации."""

    __test__ = False  # не тестовый класс, просто имя совпало с pytest-конвенцией

    date: dt.date
    q_oil: float
    q_liquid: float
    q_water: float
    q_gas: float | None = None


@dataclass
class ResolvedRates:
    well_id: int
    rates: dict[str, float]  # phase -> дебит
    method: str  # "measured" | "extrapolated" | "analog"
    confidence: str  # "high" | "medium" | "low"
    source_date: dt.date | None  # дата исходного замера (None для analog)


@dataclass
class WellDayInput:
    well_id: int
    rates: ResolvedRates
    ke: float
    ke_source: str  # "telemetry" | "downtime_log" | "daily_report" | "no_data"


@dataclass
class WellAllocationOutput:
    well_id: int
    allocated: dict[str, float] = field(default_factory=dict)  # phase -> аллоцированная добыча
    allocation_factor: dict[str, float | None] = field(default_factory=dict)  # phase -> K
    allocation_method: str = ""
    confidence: str = ""
    ke: float = 0.0
    warnings: list[str] = field(default_factory=list)


# --- КЭ --------------------------------------------------------------------


def ke_from_hours_down(hours_down: float) -> float:
    return max(0.0, min(1.0, (24.0 - hours_down) / 24.0))


def resolve_ke(
    telemetry_hours_down: float | None,
    downtime_hours_down: float | None,
    rapport_hours_on: float | None,
) -> tuple[float, str]:
    """Приоритет источника: телеметрия тока ЭЦН > журнал простоев > суточный рапорт."""
    if telemetry_hours_down is not None:
        return ke_from_hours_down(telemetry_hours_down), "telemetry"
    if downtime_hours_down is not None:
        return ke_from_hours_down(downtime_hours_down), "downtime_log"
    if rapport_hours_on is not None:
        return max(0.0, min(1.0, rapport_hours_on / 24.0)), "daily_report"
    return 1.0, "no_data"


# --- резолюция дебита скважины (measured / extrapolated / analog) -------------


def confidence_for_age(age_days: int, cfg: dict) -> str:
    bands = cfg["confidence_bands"]
    if age_days <= bands["high_max_age_days"]:
        return "high"
    if age_days <= bands["medium_max_age_days"]:
        return "medium"
    return "low"


def extrapolate_exponential(points: list[tuple[dt.date, float | None]], target_date: dt.date) -> float:
    """Простая экспоненциальная экстраполяция по первой и последней точке окна.

    points — (дата, значение), хронологически по возрастанию, обычно 2-3 точки.
    """
    pts = [(d, v) for d, v in points if v is not None and v > 0]
    if not pts:
        return 0.0
    if len(pts) == 1:
        return pts[0][1]  # нет базы для темпа — переносим последнее значение как есть

    (d0, v0), (d1, v1) = pts[0], pts[-1]
    days = (d1 - d0).days
    if days <= 0:
        return v1

    daily_rate = (v1 / v0) ** (1.0 / days)
    extra_days = (target_date - d1).days
    return v1 * (daily_rate**extra_days)


def resolve_well_rates(
    well_id: int,
    valid_tests: list[TestPoint],
    target_date: dt.date,
    analog_candidates: list[TestPoint],
    cfg: dict,
) -> ResolvedRates | None:
    """valid_tests — валидные замеры скважины с датой <= target_date, по
    возрастанию даты. analog_candidates — свежие валидные замеры скважин
    того же объекта (для метода 'analog'), уже отфильтрованные по свежести
    вызывающей стороной. None — если аллоцировать скважину нечем вообще."""

    if valid_tests:
        last = valid_tests[-1]
        age_days = (target_date - last.date).days

        if age_days <= cfg["max_test_age_days"]:
            rates = {phase: getattr(last, attr) or 0.0 for phase, attr in _TEST_ATTR.items()}
            return ResolvedRates(
                well_id=well_id,
                rates=rates,
                method="measured",
                confidence=confidence_for_age(age_days, cfg),
                source_date=last.date,
            )

        trend_n = cfg["extrapolation"]["trend_tests_count"]
        recent = valid_tests[-trend_n:]
        rates = {
            phase: extrapolate_exponential([(t.date, getattr(t, attr)) for t in recent], target_date)
            for phase, attr in _TEST_ATTR.items()
        }
        return ResolvedRates(
            well_id=well_id, rates=rates, method="extrapolated", confidence="low", source_date=last.date
        )

    if analog_candidates:
        rates = {}
        for phase, attr in _TEST_ATTR.items():
            values = [getattr(t, attr) for t in analog_candidates if getattr(t, attr) is not None]
            rates[phase] = median(values) if values else 0.0
        return ResolvedRates(well_id=well_id, rates=rates, method="analog", confidence="low", source_date=None)

    return None


# --- аллокация по узлу/суткам --------------------------------------------------


def _round_with_residual_correction(values: dict[int, float], target_total: float, decimals: int = 2) -> dict[int, float]:
    """Округляет и корректирует остаток на крупнейшую скважину, чтобы сумма
    ТОЧНО совпадала с target_total — иначе набегает копеечный дрейф округления."""
    rounded = {k: round(v, decimals) for k, v in values.items()}
    if not rounded:
        return rounded
    target_rounded = round(target_total, decimals)
    residual = round(target_rounded - sum(rounded.values()), decimals)
    if residual:
        biggest = max(rounded, key=lambda k: rounded[k])
        rounded[biggest] = round(rounded[biggest] + residual, decimals)
    return rounded


def allocate_node_day(
    well_inputs: list[WellDayInput], node_fact: dict[str, float | None], k_bounds: dict
) -> list[WellAllocationOutput]:
    """node_fact — {"oil": ..., "liquid": ..., "water": ..., "gas": ...},
    значение None означает "факта по этой фазе нет" (не путать с 0 — на
    узле реально может быть 0 газа, например)."""

    outputs: dict[int, WellAllocationOutput] = {
        wi.well_id: WellAllocationOutput(
            well_id=wi.well_id,
            allocation_method=wi.rates.method,
            confidence=wi.rates.confidence,
            ke=wi.ke,
        )
        for wi in well_inputs
    }

    for phase in PHASES:
        fact = node_fact.get(phase)
        measured = {wi.well_id: (wi.rates.rates.get(phase) or 0.0) * wi.ke for wi in well_inputs}
        wells_sum = sum(measured.values())

        k: float | None
        if fact is None or wells_sum <= 0:
            k = None
        else:
            k = fact / wells_sum
            if not (k_bounds["min"] <= k <= k_bounds["max"]):
                for wi in well_inputs:
                    outputs[wi.well_id].warnings.append(f"k_out_of_bounds:{phase}")

        for wi in well_inputs:
            outputs[wi.well_id].allocation_factor[phase] = k

        if k is None:
            for wi in well_inputs:
                outputs[wi.well_id].allocated[phase] = round(measured[wi.well_id] * 0.0, 2)
            if fact is not None and wells_sum <= 0 and fact != 0:
                for wi in well_inputs:
                    outputs[wi.well_id].warnings.append(f"no_measured_basis:{phase}")
            continue

        raw_allocated = {wid: base * k for wid, base in measured.items()}
        rounded = _round_with_residual_correction(raw_allocated, fact)
        for wid, value in rounded.items():
            outputs[wid].allocated[phase] = value

    return list(outputs.values())
