"""Быстрый анализ помесячной добычи по скважине — чистые функции без БД
(оркестрация с БД — monthly_analysis_runner.py, тот же принцип, что и в
остальных src/calc/*). Никакого Арпса и подгонки кривых — то, что нужно
"быстро посчитать": последний месяц, дельта к предыдущему, накопленная
добыча, обводнённость.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass
class MonthlyPoint:
    period_month: dt.date
    q_oil_t: float
    q_liquid_t: float
    q_water_t: float
    water_cut_pct: float | None
    q_oil_rate_t_d: float | None


@dataclass
class WellMonthlySummary:
    well_id: int
    last_period: dt.date
    q_oil_t: float
    q_oil_rate_t_d: float | None
    water_cut_pct: float | None
    prev_q_oil_t: float | None
    delta_oil_t: float | None
    delta_oil_pct: float | None
    cumulative_oil_t: float
    months_count: int


def summarize_well(well_id: int, points: list[MonthlyPoint]) -> WellMonthlySummary | None:
    """points — помесячные точки одной скважины, отсортированные по
    period_month по возрастанию. Пустой список — скважина без данных,
    вызывающий код сам решает, показывать её или пропустить."""
    if not points:
        return None

    last = points[-1]
    prev = points[-2] if len(points) >= 2 else None

    delta_oil_t = last.q_oil_t - prev.q_oil_t if prev is not None else None
    delta_oil_pct = (
        round(100 * delta_oil_t / prev.q_oil_t, 1) if prev is not None and prev.q_oil_t > 0 else None
    )

    return WellMonthlySummary(
        well_id=well_id,
        last_period=last.period_month,
        q_oil_t=last.q_oil_t,
        q_oil_rate_t_d=last.q_oil_rate_t_d,
        water_cut_pct=last.water_cut_pct,
        prev_q_oil_t=prev.q_oil_t if prev is not None else None,
        delta_oil_t=round(delta_oil_t, 2) if delta_oil_t is not None else None,
        delta_oil_pct=delta_oil_pct,
        cumulative_oil_t=round(sum(p.q_oil_t for p in points), 2),
        months_count=len(points),
    )
