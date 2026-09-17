"""DB-обвязка над src/calc/monthly_analysis.py: читает monthly_production,
собирает сводку по одной скважине или сразу по многим (для фонда/дашборда)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.calc.monthly_analysis import MonthlyPoint, WellMonthlySummary, summarize_well
from src.domain.monthly_production import MonthlyProduction


def _load_points(session: Session, well_id: int, since: dt.date | None = None) -> list[MonthlyPoint]:
    q = select(MonthlyProduction).where(MonthlyProduction.well_id == well_id)
    if since is not None:
        q = q.where(MonthlyProduction.period_month >= since)
    q = q.order_by(MonthlyProduction.period_month)
    rows = session.execute(q).scalars().all()
    return [
        MonthlyPoint(
            period_month=r.period_month,
            q_oil_t=r.q_oil_t,
            q_liquid_t=r.q_liquid_t,
            q_water_t=r.q_water_t,
            water_cut_pct=r.water_cut_pct,
            q_oil_rate_t_d=r.q_oil_rate_t_d,
        )
        for r in rows
    ]


def get_well_summary(session: Session, well_id: int, since: dt.date | None = None) -> WellMonthlySummary | None:
    points = _load_points(session, well_id, since)
    return summarize_well(well_id, points)


def summarize_wells(
    session: Session, well_ids: list[int], since: dt.date | None = None
) -> list[WellMonthlySummary]:
    """Сводка по многим скважинам сразу (фонд/дашборд) — по одному простому
    запросу на скважину, без объединяющих join'ов и переусложнения."""
    summaries = []
    for well_id in well_ids:
        summary = get_well_summary(session, well_id, since)
        if summary is not None:
            summaries.append(summary)
    return summaries
