"""Метрики качества данных за период: карантин загрузки, забракованные
замеры, скважины без свежих замеров, низкая уверенность аллокации."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.cache import cache
from src.api.deps import get_current_user, get_db
from src.api.schemas.data_quality import DataQualityMetrics
from src.domain.ingestion_log import IngestionQuarantine, IngestionRun
from src.domain.master_data import Well
from src.domain.timeseries import DailyProduction, WellTest

router = APIRouter(prefix="/api/data-quality", tags=["data-quality"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=DataQualityMetrics)
def get_data_quality(
    from_: dt.date = Query(..., alias="from"),
    to: dt.date = Query(...),
    db: Session = Depends(get_db),
) -> DataQualityMetrics:
    return cache.get_or_set(f"data-quality:{from_}:{to}", lambda: _compute(db, from_, to))


def _compute(db: Session, from_: dt.date, to: dt.date) -> DataQualityMetrics:
    lower = dt.datetime.combine(from_, dt.time.min, tzinfo=dt.timezone.utc)
    upper = dt.datetime.combine(to, dt.time.max, tzinfo=dt.timezone.utc)

    quarantined = db.execute(
        select(func.count())
        .select_from(IngestionQuarantine)
        .join(IngestionRun, IngestionRun.id == IngestionQuarantine.run_id)
        .where(IngestionRun.started_at.between(lower, upper))
    ).scalar_one()

    invalid_tests = db.execute(
        select(func.count()).select_from(WellTest).where(
            WellTest.ts_start.between(lower, upper), WellTest.is_valid.is_(False)
        )
    ).scalar_one()
    valid_tests = db.execute(
        select(func.count()).select_from(WellTest).where(
            WellTest.ts_start.between(lower, upper), WellTest.is_valid.is_(True)
        )
    ).scalar_one()

    tested_well_ids = set(
        db.execute(
            select(WellTest.well_id.distinct()).where(WellTest.ts_start.between(lower, upper))
        ).scalars().all()
    )
    active_well_ids = set(
        db.execute(select(Well.id).where(Well.well_type == "producer", Well.status == "active")).scalars().all()
    )
    wells_without_recent_test = len(active_well_ids - tested_well_ids)

    low_confidence_days = db.execute(
        select(func.count()).select_from(DailyProduction).where(
            DailyProduction.date.between(from_, to), DailyProduction.confidence == "low"
        )
    ).scalar_one()

    return DataQualityMetrics(
        period_start=from_,
        period_end=to,
        quarantined_records=quarantined,
        invalid_tests=invalid_tests,
        valid_tests=valid_tests,
        wells_without_recent_test=wells_without_recent_test,
        low_confidence_allocation_days=low_confidence_days,
    )
