"""DB-обвязка для помесячной оценки потерь от простоя (см.
src/calc/monthly_loss.py) — измерения (узел/объект/месторождение)
переиспользуются из src/calc/deferred_runner.py, это та же топология
скважина -> узел/объект/месторождение, что и для суточных потерь."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.calc.deferred_runner import _well_dimension_maps
from src.calc.monthly_loss import MonthlyLossInput, compute_month_loss
from src.domain.monthly_production import MonthlyProduction
from src.ingestion.base import Period


def aggregate_monthly_losses(
    session: Session, period: Period, group_by: str = "well", well_ids: list[int] | None = None
) -> list[dict]:
    """group_by: 'well' | 'node' (= куст) | 'reservoir' (объект) | 'field'
    (месторождение). Бакет по времени всегда месяц — гранулярность самих
    данных, дробить дальше некуда."""
    if group_by not in ("well", "node", "reservoir", "field"):
        raise ValueError(f"неизвестный group_by: {group_by!r}")

    q = select(MonthlyProduction).where(
        MonthlyProduction.period_month.between(period.start.replace(day=1), period.end.replace(day=1))
    )
    if well_ids:
        q = q.where(MonthlyProduction.well_id.in_(well_ids))
    rows = session.execute(q).scalars().all()

    lines = [
        compute_month_loss(
            MonthlyLossInput(
                well_id=r.well_id,
                period_month=r.period_month,
                calendar_days=r.calendar_days,
                working_days=r.working_days,
                q_oil_rate_t_d=r.q_oil_rate_t_d,
            )
        )
        for r in rows
    ]
    lines = [line for line in lines if line is not None]
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
