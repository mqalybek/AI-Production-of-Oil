"""Сводка по помесячной добыче сразу по многим скважинам — для фонда/дашборда,
чтобы не дёргать /api/wells/{uwi}/monthly-summary по одной скважине за раз."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, get_db
from src.api.schemas.common import Page
from src.api.schemas.wells import WellMonthlySummaryOut
from src.calc.monthly_analysis_runner import summarize_wells
from src.domain.master_data import Well

router = APIRouter(prefix="/api/monthly-production", tags=["monthly-production"], dependencies=[Depends(get_current_user)])


@router.get("/wells", response_model=Page[WellMonthlySummaryOut])
def list_monthly_summaries(
    field_id: int | None = Query(None, alias="field"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[WellMonthlySummaryOut]:
    q = select(Well.id, Well.uwi)
    if field_id is not None:
        q = q.where(Well.field_id == field_id)
    q = q.order_by(Well.uwi)
    wells = db.execute(q).all()
    uwi_by_id = {w.id: w.uwi for w in wells}

    summaries = summarize_wells(db, [w.id for w in wells])
    items = [
        WellMonthlySummaryOut(uwi=uwi_by_id.get(s.well_id), **s.__dict__)
        for s in sorted(summaries, key=lambda s: uwi_by_id.get(s.well_id, ""))
    ]
    return Page(items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset)
