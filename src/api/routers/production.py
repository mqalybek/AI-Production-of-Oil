"""Сводки по добыче: сутки по месторождению и план/факт по периодам."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, get_db
from src.api.schemas.production import DailyFieldSummary, ProductionSummaryPoint
from src.api.utils import bucket_date
from src.domain.api_access import ProductionPlan
from src.domain.master_data import Field, Well
from src.domain.timeseries import DailyProduction
from src.ingestion.base import Period

router = APIRouter(prefix="/api/production", tags=["production"], dependencies=[Depends(get_current_user)])


@router.get("/daily", response_model=list[DailyFieldSummary])
def get_daily_summary(
    field_id: int | None = Query(None, alias="field"),
    date: dt.date = Query(...),
    db: Session = Depends(get_db),
) -> list[DailyFieldSummary]:
    fields_q = select(Field)
    if field_id is not None:
        fields_q = fields_q.where(Field.id == field_id)
    fields = db.execute(fields_q).scalars().all()

    result = []
    for f in fields:
        agg = db.execute(
            select(
                func.coalesce(func.sum(DailyProduction.q_oil_t), 0.0),
                func.coalesce(func.sum(DailyProduction.q_liquid_t), 0.0),
                func.coalesce(func.sum(DailyProduction.q_water_m3), 0.0),
            )
            .join(Well, Well.id == DailyProduction.well_id)
            .where(Well.field_id == f.id, DailyProduction.date == date)
        ).one()
        wells_active = db.execute(
            select(func.count())
            .select_from(DailyProduction)
            .join(Well, Well.id == DailyProduction.well_id)
            .where(Well.field_id == f.id, DailyProduction.date == date, DailyProduction.hours_on > 0)
        ).scalar_one()
        wells_stopped = db.execute(
            select(func.count())
            .select_from(DailyProduction)
            .join(Well, Well.id == DailyProduction.well_id)
            .where(Well.field_id == f.id, DailyProduction.date == date, DailyProduction.hours_on == 0)
        ).scalar_one()
        result.append(
            DailyFieldSummary(
                field_id=f.id,
                field_name=f.name,
                date=date,
                q_oil_t=round(agg[0], 2),
                q_liquid_t=round(agg[1], 2),
                q_water_m3=round(agg[2], 2),
                wells_active=wells_active,
                wells_stopped=wells_stopped,
            )
        )
    return result


@router.get("/summary", response_model=list[ProductionSummaryPoint])
def get_production_summary(
    period: str = Query(..., description="YYYY-MM или YYYY-MM-DD"),
    field_id: int | None = Query(None, alias="field"),
    granularity: str = Query("month"),
    db: Session = Depends(get_db),
) -> list[ProductionSummaryPoint]:
    try:
        parsed = Period.parse(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    q = select(DailyProduction.date, DailyProduction.q_oil_t).where(
        DailyProduction.date.between(parsed.start, parsed.end)
    )
    if field_id is not None:
        q = q.join(Well, Well.id == DailyProduction.well_id).where(Well.field_id == field_id)

    try:
        buckets: dict[dt.date, float] = defaultdict(float)
        for date, q_oil_t in db.execute(q).all():
            buckets[bucket_date(date, granularity)] += q_oil_t
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    plan_q = select(ProductionPlan.period_month, func.sum(ProductionPlan.planned_oil_t)).where(
        ProductionPlan.period_month.between(parsed.start.replace(day=1), parsed.end)
    )
    if field_id is not None:
        plan_q = plan_q.where(ProductionPlan.field_id == field_id)
    plan_q = plan_q.group_by(ProductionPlan.period_month)
    plan_by_month = {month: total for month, total in db.execute(plan_q).all()}

    result = []
    for point, q_oil_t in sorted(buckets.items()):
        plan_key = point.replace(day=1)
        result.append(
            ProductionSummaryPoint(period=point, q_oil_t=round(q_oil_t, 2), plan_oil_t=plan_by_month.get(plan_key))
        )
    return result
