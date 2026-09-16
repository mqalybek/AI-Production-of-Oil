"""Потери добычи = (потенциал − факт) × время, разложенные по причине.

Три базы потенциала считаются параллельно (см. potential_from_*), но в
deferred_production идёт одна — по приоритету
model_forecast > decline_trend > last_valid_test (согласовано с автором,
см. ADR в CLAUDE.md).

Ключевая формула — разложение недобора нефти на две составляющие при
работающей скважине (Qн = Qж × (1 − WC), точное аддитивное разложение,
без остатка):

    потери_снижение_режима = max(0, (Qж_пот − Qж_факт) × (1 − WC_факт))
    потери_обводнение      = max(0, Qж_пот × (WC_факт − WC_пот))

Чистая математика — без обращения к БД (тестируется без сессии). Сборку
входных данных из БД делает src/calc/deferred_runner.py.
"""

from __future__ import annotations

import datetime as dt
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import curve_fit

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "deferred_rules.yaml"


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
class ProductionPoint:
    date: dt.date
    q_oil: float
    q_liquid: float


@dataclass
class PotentialEstimate:
    q_liquid_rate: float  # т/сут — если бы скважина работала все 24 часа
    q_oil_rate: float
    water_cut: float  # доля 0..1
    basis: str  # "last_valid_test" | "decline_trend" | "model_forecast"
    r2: float | None = None  # диагностика подгонки (только decline_trend)


@dataclass
class DowntimeInterval:
    reason_id: int
    hours: float


@dataclass
class DeferredLossLine:
    category: str  # "downtime" | "rate_reduction" | "watering" | "idle_fund"
    reason_id: int | None
    volume_oil_t: float
    potential_basis: str


# --- подгонка кривых падения --------------------------------------------------


def arps_hyperbolic(t: np.ndarray, qi: float, b: float, di: float) -> np.ndarray:
    return qi / (1.0 + b * di * t) ** (1.0 / b)


def _r_squared(actual: np.ndarray, predicted: np.ndarray) -> float:
    ss_res = float(np.sum((actual - predicted) ** 2))
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1.0 - ss_res / ss_tot


def _try_hyperbolic(t: np.ndarray, q: np.ndarray, cfg: dict) -> tuple[float, float, float, float] | None:
    if np.all(q <= 0):
        return None
    b_bounds = cfg["b_bounds"]
    di_min = cfg["di_min"]
    try:
        popt, _ = curve_fit(
            arps_hyperbolic,
            t,
            q,
            p0=[max(float(q[-1]), 1e-3), 0.3, max(di_min, 0.01)],
            bounds=([1e-6, b_bounds["min"], di_min], [np.inf, max(b_bounds["max"], di_min * 2), 1.0]),
            maxfev=5000,
        )
    except (RuntimeError, ValueError):
        return None
    qi, b, di = (float(x) for x in popt)
    r2 = _r_squared(q, arps_hyperbolic(t, qi, b, di))
    return qi, b, di, r2


def fit_exponential(t: np.ndarray, q: np.ndarray) -> tuple[float, float, float] | None:
    """qi, Di через лог-линейную регрессию (log q = log qi − Di·t) — надёжный
    фоллбэк, когда гиперболическая подгонка не сошлась или не годится."""
    positive = q > 0
    if positive.sum() < 2:
        return None
    t_pos, log_q = t[positive], np.log(q[positive])
    design = np.vstack([np.ones_like(t_pos), -t_pos]).T
    (log_qi, di), *_ = np.linalg.lstsq(design, log_q, rcond=None)
    qi, di = float(np.exp(log_qi)), max(float(di), 0.0)
    r2 = _r_squared(q[positive], qi * np.exp(-di * t_pos))
    return qi, di, r2


def _fit_rate_gated(t: np.ndarray, q: np.ndarray, target_t: float, cfg: dict) -> tuple[float, str, float] | None:
    """Гипербола (если R² >= порога) -> экспонента -> None."""
    if len(q) < cfg["min_points"] or np.all(q <= 0):
        return None

    hyp = _try_hyperbolic(t, q, cfg)
    if hyp is not None and hyp[3] >= cfg["r2_threshold"]:
        qi, b, di, r2 = hyp
        return float(arps_hyperbolic(np.array([target_t]), qi, b, di)[0]), "hyperbolic", r2

    exp = fit_exponential(t, q)
    if exp is not None:
        qi, di, r2 = exp
        return float(qi * np.exp(-di * target_t)), "exponential", r2

    return None


def _fit_rate_best_effort(t: np.ndarray, q: np.ndarray, target_t: float, cfg: dict) -> float:
    """Как _fit_rate_gated, но никогда не сдаётся — на крайний случай несёт
    вперёд последнее значение. Используется для Qж внутри decline_trend —
    решение о самой базе decline_trend принимается по качеству кривой Qн."""
    result = _fit_rate_gated(t, q, target_t, cfg)
    if result is not None:
        return result[0]
    return float(q[-1]) if len(q) else 0.0


# --- три базы потенциала -------------------------------------------------------


def potential_from_last_valid_test(last_test: object | None) -> PotentialEstimate | None:
    """last_test — объект с полями q_oil, q_liquid (например, WellTest)."""
    if last_test is None:
        return None
    q_liq, q_oil = last_test.q_liquid, last_test.q_oil
    water_cut = 0.0 if q_liq <= 0 else max(0.0, min(1.0, 1.0 - q_oil / q_liq))
    return PotentialEstimate(q_liquid_rate=q_liq, q_oil_rate=q_oil, water_cut=water_cut, basis="last_valid_test")


def potential_from_decline_trend(
    history: list[ProductionPoint], target_date: dt.date, cfg: dict
) -> PotentialEstimate | None:
    """history — факт добычи (daily_production) за последние 6-12 мес,
    хронологически по возрастанию. cfg — полный резолвленный конфиг (как из
    resolve_config), сама секция decline_trend достаётся здесь. None — Арпс
    и экспонента обе не годятся, вызывающая сторона должна откатиться на
    last_valid_test."""
    dt_cfg = cfg["decline_trend"]
    if len(history) < dt_cfg["min_points"]:
        return None

    t0 = history[0].date
    t = np.array([(p.date - t0).days for p in history], dtype=float)
    target_t = float((target_date - t0).days)

    oil_result = _fit_rate_gated(t, np.array([p.q_oil for p in history]), target_t, dt_cfg)
    if oil_result is None:
        return None

    oil_rate, _method, r2 = oil_result
    oil_rate = max(0.0, oil_rate)
    liq_rate = max(oil_rate, _fit_rate_best_effort(t, np.array([p.q_liquid for p in history]), target_t, dt_cfg))
    water_cut = 0.0 if liq_rate <= 0 else max(0.0, min(1.0, 1.0 - oil_rate / liq_rate))

    return PotentialEstimate(
        q_liquid_rate=liq_rate, q_oil_rate=oil_rate, water_cut=water_cut, basis="decline_trend", r2=r2
    )


def potential_from_model_forecast(well_id: int, target_date: dt.date) -> PotentialEstimate | None:
    """Интерфейс на будущее (шаг 9 — интеграция гидродинамической модели).
    Пока всегда None: источника прогноза ещё нет."""
    return None


def pick_primary_potential(
    model: PotentialEstimate | None, decline: PotentialEstimate | None, last_test: PotentialEstimate | None
) -> PotentialEstimate | None:
    """Приоритет: model_forecast > decline_trend > last_valid_test."""
    for candidate in (model, decline, last_test):
        if candidate is not None:
            return candidate
    return None


# --- разложение потерь на сутки -------------------------------------------------


def compute_day_losses(
    potential: PotentialEstimate,
    hours_on: float,
    q_oil_actual: float,
    q_liquid_actual: float,
    downtime_intervals: list[DowntimeInterval],
) -> list[DeferredLossLine]:
    hours_on = max(0.0, min(24.0, hours_on))
    lines: list[DeferredLossLine] = []

    for interval in downtime_intervals:
        loss = potential.q_oil_rate * (interval.hours / 24.0)
        if loss > 0:
            lines.append(DeferredLossLine("downtime", interval.reason_id, round(loss, 4), potential.basis))

    q_liq_potential_on = potential.q_liquid_rate * (hours_on / 24.0)
    water_cut_actual = (
        0.0 if q_liquid_actual <= 0 else max(0.0, min(1.0, 1.0 - q_oil_actual / q_liquid_actual))
    )

    rate_loss = max(0.0, (q_liq_potential_on - q_liquid_actual) * (1.0 - water_cut_actual))
    watering_loss = max(0.0, q_liq_potential_on * (water_cut_actual - potential.water_cut))

    if rate_loss > 0:
        lines.append(DeferredLossLine("rate_reduction", None, round(rate_loss, 4), potential.basis))
    if watering_loss > 0:
        lines.append(DeferredLossLine("watering", None, round(watering_loss, 4), potential.basis))

    return lines


def compute_idle_fund_loss(potential: PotentialEstimate) -> DeferredLossLine:
    """Скважина в бездействии/консервации — весь день потенциальной нефти потерян."""
    return DeferredLossLine("idle_fund", None, round(potential.q_oil_rate, 4), potential.basis)
