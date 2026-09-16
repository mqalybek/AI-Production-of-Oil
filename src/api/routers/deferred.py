"""Потери добычи: агрегация по измерению (скважина/узел/объект/месторождение)
или Парето по причинам — переиспользует src/calc/deferred_runner.py."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.cache import cache
from src.api.deps import get_current_user, get_db
from src.api.schemas.deferred import DeferredAggregateItem, DeferredParetoItem
from src.calc.deferred_runner import aggregate_losses, pareto_by_reason
from src.domain.reference import DowntimeReason
from src.ingestion.base import Period

router = APIRouter(prefix="/api/deferred", tags=["deferred"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[DeferredAggregateItem] | list[DeferredParetoItem])
def get_deferred(
    from_: dt.date = Query(..., alias="from"),
    to: dt.date = Query(...),
    groupby: str = Query("well", description="well|node|reservoir|field|reason"),
    granularity: str = Query("day", description="день/неделя/месяц/ytd — только для groupby != reason"),
    db: Session = Depends(get_db),
):
    period = Period(from_, to)
    cache_key = f"deferred:{from_}:{to}:{groupby}:{granularity}"

    if groupby == "reason":
        rows = cache.get_or_set(cache_key, lambda: pareto_by_reason(db, period))
        reason_names = {
            r.id: r.name for r in db.execute(select(DowntimeReason)).scalars().all()
        }
        return [
            DeferredParetoItem(
                category=r["category"],
                reason_id=r["reason_id"],
                reason_name=reason_names.get(r["reason_id"]),
                volume_oil_t=r["volume_oil_t"],
                share_pct=r["share_pct"],
                cumulative_pct=r["cumulative_pct"],
            )
            for r in rows
        ]

    try:
        rows = cache.get_or_set(
            cache_key, lambda: aggregate_losses(db, period, group_by=groupby, time_bucket=granularity)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return [DeferredAggregateItem(**r) for r in rows]
