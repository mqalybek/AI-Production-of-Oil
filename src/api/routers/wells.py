"""Карточка скважины и все данные по ней: паспорт, добыча, замеры,
телеметрия, единая шкала событий (ГТМ/ремонты/простои)."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, get_db
from src.api.schemas.common import Page
from src.api.schemas.wells import (
    CompletionOut,
    DailyProductionOut,
    EquipmentOut,
    TelemetryPoint,
    WellCard,
    WellEvent,
    WellListItem,
    WellTestOut,
)
from src.api.utils import bucket_date, paginate
from src.domain.master_data import Completion, Equipment, Well
from src.domain.reference import GtmType, MeasurementTag
from src.domain.timeseries import DailyProduction, Downtime, GtmEvent, Measurement, WellTest

router = APIRouter(prefix="/api/wells", tags=["wells"], dependencies=[Depends(get_current_user)])


def _get_well_or_404(db: Session, uwi: str) -> Well:
    well = db.execute(select(Well).where(Well.uwi == uwi)).scalar_one_or_none()
    if well is None:
        raise HTTPException(status_code=404, detail=f"скважина {uwi!r} не найдена")
    return well


@router.get("", response_model=Page[WellListItem])
def list_wells(
    field_id: int | None = None,
    status: str | None = None,
    reservoir_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[WellListItem]:
    q = select(Well)
    if field_id is not None:
        q = q.where(Well.field_id == field_id)
    if status is not None:
        q = q.where(Well.status == status)
    if reservoir_id is not None:
        q = q.join(Completion, Completion.well_id == Well.id).where(Completion.reservoir_id == reservoir_id)
    q = q.order_by(Well.uwi)

    rows = db.execute(q).scalars().unique().all()
    return Page(items=paginate(rows, limit, offset), total=len(rows), limit=limit, offset=offset)


@router.get("/{uwi}", response_model=WellCard)
def get_well_card(uwi: str, db: Session = Depends(get_db)) -> WellCard:
    well = _get_well_or_404(db, uwi)
    equipment = db.execute(
        select(Equipment).where(Equipment.well_id == well.id).order_by(Equipment.install_date.desc())
    ).scalars().all()
    completions = db.execute(
        select(Completion).where(Completion.well_id == well.id).order_by(Completion.perf_date.desc())
    ).scalars().all()
    return WellCard(
        id=well.id,
        uwi=well.uwi,
        gos_number=well.gos_number,
        name=well.name,
        field_id=well.field_id,
        well_type=well.well_type,
        status=well.status,
        spud_date=well.spud_date,
        equipment=[EquipmentOut.model_validate(e) for e in equipment],
        completions=[CompletionOut.model_validate(c) for c in completions],
    )


@router.get("/{uwi}/production", response_model=list[DailyProductionOut])
def get_well_production(
    uwi: str,
    from_: dt.date = Query(..., alias="from"),
    to: dt.date = Query(...),
    granularity: str = Query("day"),
    db: Session = Depends(get_db),
) -> list[DailyProductionOut]:
    well = _get_well_or_404(db, uwi)
    rows = db.execute(
        select(DailyProduction)
        .where(DailyProduction.well_id == well.id, DailyProduction.date.between(from_, to))
        .order_by(DailyProduction.date)
    ).scalars().all()

    if granularity == "day":
        return [DailyProductionOut.model_validate(r) for r in rows]

    try:
        buckets: dict[dt.date, list[DailyProduction]] = defaultdict(list)
        for r in rows:
            buckets[bucket_date(r.date, granularity)].append(r)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = []
    for period, group in sorted(buckets.items()):
        n = len(group)
        result.append(
            DailyProductionOut(
                date=period,
                q_oil_t=round(sum(g.q_oil_t for g in group), 2),
                q_liquid_t=round(sum(g.q_liquid_t for g in group), 2),
                q_water_m3=round(sum(g.q_water_m3 for g in group), 2),
                q_gas_m3=round(sum(g.q_gas_m3 or 0 for g in group), 2) if any(g.q_gas_m3 for g in group) else None,
                hours_on=round(sum(g.hours_on for g in group) / n, 2),
                ke=round(sum(g.ke for g in group) / n, 3),
                allocation_method=None,
                confidence=None,
            )
        )
    return result


@router.get("/{uwi}/tests", response_model=Page[WellTestOut])
def get_well_tests(
    uwi: str,
    from_: dt.date | None = Query(None, alias="from"),
    to: dt.date | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[WellTestOut]:
    well = _get_well_or_404(db, uwi)
    q = select(WellTest).where(WellTest.well_id == well.id)
    if from_ is not None:
        q = q.where(WellTest.ts_start >= dt.datetime.combine(from_, dt.time.min, tzinfo=dt.timezone.utc))
    if to is not None:
        q = q.where(WellTest.ts_start <= dt.datetime.combine(to, dt.time.max, tzinfo=dt.timezone.utc))
    q = q.order_by(WellTest.ts_start.desc())

    rows = db.execute(q).scalars().all()
    return Page(items=paginate(rows, limit, offset), total=len(rows), limit=limit, offset=offset)


@router.get("/{uwi}/telemetry", response_model=list[TelemetryPoint])
def get_well_telemetry(
    uwi: str,
    from_: dt.datetime = Query(..., alias="from"),
    to: dt.datetime = Query(...),
    tags: str | None = Query(None, description="коды тегов через запятую, например p_buf,p_zatr"),
    db: Session = Depends(get_db),
) -> list[TelemetryPoint]:
    well = _get_well_or_404(db, uwi)
    q = (
        select(Measurement, MeasurementTag.code)
        .join(MeasurementTag, MeasurementTag.id == Measurement.tag_id)
        .where(Measurement.well_id == well.id, Measurement.ts.between(from_, to))
    )
    if tags:
        tag_codes = [t.strip() for t in tags.split(",") if t.strip()]
        q = q.where(MeasurementTag.code.in_(tag_codes))
    q = q.order_by(Measurement.ts)

    rows = db.execute(q).all()
    return [
        TelemetryPoint(ts=m.ts, tag=code, value=m.value, quality=m.quality) for m, code in rows
    ]


@router.get("/{uwi}/events", response_model=list[WellEvent])
def get_well_events(
    uwi: str,
    from_: dt.date | None = Query(None, alias="from"),
    to: dt.date | None = Query(None),
    db: Session = Depends(get_db),
) -> list[WellEvent]:
    well = _get_well_or_404(db, uwi)
    events: list[WellEvent] = []

    gtm_q = select(GtmEvent, GtmType.name).join(GtmType, GtmType.id == GtmEvent.gtm_type_id).where(
        GtmEvent.well_id == well.id
    )
    if from_ is not None:
        gtm_q = gtm_q.where(GtmEvent.event_date >= from_)
    if to is not None:
        gtm_q = gtm_q.where(GtmEvent.event_date <= to)
    for gtm, type_name in db.execute(gtm_q).all():
        events.append(WellEvent(kind="gtm", date=gtm.event_date, title=type_name, detail=gtm.description))

    eq_q = select(Equipment).where(Equipment.well_id == well.id)
    for eq in db.execute(eq_q).scalars().all():
        if from_ is None or eq.install_date >= from_:
            if to is None or eq.install_date <= to:
                events.append(
                    WellEvent(kind="equipment", date=eq.install_date, title=f"Спуск {eq.equipment_type}", detail=eq.type_size)
                )
        if eq.pull_date is not None:
            if (from_ is None or eq.pull_date >= from_) and (to is None or eq.pull_date <= to):
                events.append(
                    WellEvent(kind="equipment", date=eq.pull_date, title=f"Подъём {eq.equipment_type}", detail=eq.type_size)
                )

    dt_q = select(Downtime).where(Downtime.well_id == well.id)
    for downtime in db.execute(dt_q).scalars().all():
        event_date = downtime.ts_start.date()
        if (from_ is None or event_date >= from_) and (to is None or event_date <= to):
            events.append(
                WellEvent(
                    kind="downtime",
                    date=event_date,
                    title="Простой",
                    detail=downtime.comment,
                )
            )

    events.sort(key=lambda e: e.date)
    return events
