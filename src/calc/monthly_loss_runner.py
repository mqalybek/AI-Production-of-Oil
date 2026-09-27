"""DB-обвязка для помесячной оценки потерь от простоя (см.
src/calc/monthly_loss.py) — измерения (узел/объект/месторождение)
переиспользуются из src/calc/deferred_runner.py, это та же топология
скважина -> узел/объект/месторождение, что и для суточных потерь."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.calc.deferred import load_raw_config
from src.calc.deferred_runner import _well_dimension_maps
from src.calc.monthly_loss import MonthlyLossInput, compute_month_loss
from src.domain.monthly_production import MonthlyProduction
from src.ingestion.base import Period


def aggregate_monthly_losses(
    session: Session,
    period: Period,
    group_by: str = "well",
    well_ids: list[int] | None = None,
    raw_config: dict | None = None,
) -> list[dict]:
    """group_by: 'well' | 'node' (= куст) | 'reservoir' (объект) | 'field'
    (месторождение). Бакет по времени всегда месяц — гранулярность самих
    данных, дробить дальше некуда."""
    if group_by not in ("well", "node", "reservoir", "field"):
        raise ValueError(f"неизвестный group_by: {group_by!r}")

    max_age_days = (raw_config or load_raw_config())["default"]["idle_fund"]["max_potential_age_days"]
    first_month = period.start.replace(day=1)

    # историю берём с запасом назад — для месяцев полного простоя нужен дебит
    # последнего рабочего месяца, который может лежать до начала периода
    q = select(MonthlyProduction).where(
        MonthlyProduction.period_month.between(
            first_month - dt.timedelta(days=max_age_days), period.end.replace(day=1)
        )
    )
    if well_ids:
        q = q.where(MonthlyProduction.well_id.in_(well_ids))
    q = q.order_by(MonthlyProduction.well_id, MonthlyProduction.period_month)
    rows = session.execute(q).scalars().all()

    lines = []
    last_rate: dict[int, tuple[dt.date, float]] = {}  # well_id -> (месяц, дебит) последнего рабочего месяца
    for r in rows:
        if r.period_month >= first_month:
            fallback = last_rate.get(r.well_id)
            fresh = fallback is not None and (r.period_month - fallback[0]).days <= max_age_days
            line = compute_month_loss(
                MonthlyLossInput(
                    well_id=r.well_id,
                    period_month=r.period_month,
                    calendar_days=r.calendar_days,
                    working_days=r.working_days,
                    q_oil_rate_t_d=r.q_oil_rate_t_d,
                    fallback_rate_t_d=fallback[1] if fresh else None,
                )
            )
            if line is not None:
                lines.append(line)
        if r.working_days > 0 and r.q_oil_rate_t_d is not None:
            last_rate[r.well_id] = (r.period_month, r.q_oil_rate_t_d)
    if not lines:
        return []

    dims = (
        _well_dimension_maps(session, sorted({line.well_id for line in lines}), period.end)
        if group_by != "well"
        else {}
    )

    def _group_key(well_id: int) -> int | None:
        return well_id if group_by == "well" else dims[group_by].get(well_id)

    totals: dict[tuple, float] = defaultdict(float)
    for line in lines:
        key = (_group_key(line.well_id), line.period_month)
        totals[key] += line.volume_oil_t

    return [
        {"group": g, "period": p, "category": "downtime", "volume_oil_t": round(v, 2)}
        for (g, p), v in sorted(totals.items(), key=lambda kv: (kv[0][1], kv[0][0] or 0))
    ]
