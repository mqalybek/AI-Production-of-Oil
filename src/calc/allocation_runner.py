"""Сборка входных данных для аллокации из БД + batch-прогон по периоду +
upsert в daily_production. Чистая математика — в src/calc/allocation.py.

Про производительность: запросы идут по (скважина, дата) без агрессивной
батчировки — для периодического batch-прогона (не hot path) это приемлемо,
как и в src/calc/validation_runner.py. Если станет узким местом — стоит
кэшировать историю замеров по скважине один раз, а не на каждую дату.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.calc.allocation import (
    TestPoint,
    WellAllocationOutput,
    WellDayInput,
    allocate_node_day,
    load_raw_config,
    resolve_config,
    resolve_ke,
    resolve_well_rates,
)
from src.domain.master_data import Completion, GatheringNode, WellGatheringNodeHistory
from src.domain.reference import MeasurementTag
from src.domain.timeseries import DailyProduction, Downtime, Measurement, NodeProduction, WellTest
from src.ingestion.base import Period


@dataclass
class AllocationReport:
    period_start: dt.date
    period_end: dt.date
    total_well_days: int
    allocated_well_days: int
    no_node_data_days: int  # (узел, дата) без факта — аллокация не выполнялась
    method_counts: dict[str, int] = field(default_factory=dict)
    warnings_count: dict[str, int] = field(default_factory=dict)


def _active_wells(session: Session, node_id: int, on_date: dt.date) -> list[int]:
    return list(
        session.execute(
            select(WellGatheringNodeHistory.well_id).where(
                WellGatheringNodeHistory.node_id == node_id,
                WellGatheringNodeHistory.valid_from <= on_date,
                (WellGatheringNodeHistory.valid_to.is_(None)) | (WellGatheringNodeHistory.valid_to > on_date),
            )
        ).scalars()
    )


def _valid_tests_up_to(session: Session, well_id: int, on_date: dt.date) -> list[TestPoint]:
    upper = dt.datetime.combine(on_date, dt.time.max, tzinfo=dt.timezone.utc)
    rows = session.execute(
        select(WellTest)
        .where(WellTest.well_id == well_id, WellTest.is_valid.is_(True), WellTest.ts_start <= upper)
        .order_by(WellTest.ts_start)
    ).scalars()
    return [
        TestPoint(date=r.ts_start.date(), q_oil=r.q_oil, q_liquid=r.q_liquid, q_water=r.q_water, q_gas=r.q_gas)
        for r in rows
    ]


def _analog_candidates(session: Session, well_id: int, on_date: dt.date, max_age_days: int) -> list[TestPoint]:
    reservoir_id = session.execute(
        select(Completion.reservoir_id).where(Completion.well_id == well_id).order_by(Completion.perf_date.desc())
    ).scalars().first()
    if reservoir_id is None:
        return []

    sibling_ids = list(
        session.execute(
            select(Completion.well_id).where(
                Completion.reservoir_id == reservoir_id, Completion.well_id != well_id
            )
        ).scalars()
    )
    if not sibling_ids:
        return []

    lower = dt.datetime.combine(on_date - dt.timedelta(days=max_age_days), dt.time.min, tzinfo=dt.timezone.utc)
    upper = dt.datetime.combine(on_date, dt.time.max, tzinfo=dt.timezone.utc)
    rows = session.execute(
        select(WellTest).where(
            WellTest.well_id.in_(sibling_ids), WellTest.is_valid.is_(True), WellTest.ts_start.between(lower, upper)
        )
    ).scalars()
    return [
        TestPoint(date=r.ts_start.date(), q_oil=r.q_oil, q_liquid=r.q_liquid, q_water=r.q_water, q_gas=r.q_gas)
        for r in rows
    ]


def _telemetry_hours_down(
    session: Session, current_tag_id: int | None, well_id: int, on_date: dt.date, threshold_a: float
) -> float | None:
    if current_tag_id is None:
        return None
    lower = dt.datetime.combine(on_date, dt.time.min, tzinfo=dt.timezone.utc)
    upper = dt.datetime.combine(on_date, dt.time.max, tzinfo=dt.timezone.utc)
    values = list(
        session.execute(
            select(Measurement.value).where(
                Measurement.well_id == well_id,
                Measurement.tag_id == current_tag_id,
                Measurement.ts >= lower,
                Measurement.ts <= upper,
            )
        ).scalars()
    )
    if not values:
        return None
    down_fraction = sum(1 for v in values if v < threshold_a) / len(values)
    return 24.0 * down_fraction


def _downtime_hours(session: Session, well_id: int, on_date: dt.date) -> float:
    """Всегда возвращает число (0.0, если простоев нет) — отсутствие записей в
    downtime считается достоверной информацией "проблем не было", а не
    отсутствием данных. Поэтому суточный рапорт как источник КЭ реально
    используется, только если и телеметрии, и самого журнала простоев для
    скважины ещё нет (например, до подключения этих источников)."""
    lower = dt.datetime.combine(on_date, dt.time.min, tzinfo=dt.timezone.utc)
    upper = dt.datetime.combine(on_date, dt.time.max, tzinfo=dt.timezone.utc)
    rows = session.execute(
        select(Downtime.ts_start, Downtime.ts_end).where(
            Downtime.well_id == well_id, Downtime.ts_start < upper, Downtime.ts_end > lower
        )
    ).all()
    hours = sum(
        max(0.0, (min(ts_end, upper) - max(ts_start, lower)).total_seconds() / 3600) for ts_start, ts_end in rows
    )
    return min(24.0, hours)


def _rapport_hours_on(session: Session, hours_tag_id: int | None, well_id: int, on_date: dt.date) -> float | None:
    if hours_tag_id is None:
        return None
    lower = dt.datetime.combine(on_date, dt.time.min, tzinfo=dt.timezone.utc)
    upper = dt.datetime.combine(on_date, dt.time.max, tzinfo=dt.timezone.utc)
    return session.execute(
        select(Measurement.value)
        .where(
            Measurement.well_id == well_id,
            Measurement.tag_id == hours_tag_id,
            Measurement.ts >= lower,
            Measurement.ts <= upper,
        )
        .order_by(Measurement.ts.desc())
    ).scalars().first()


def _node_fact(session: Session, node_id: int, on_date: dt.date) -> dict[str, float | None] | None:
    row = session.execute(
        select(
            NodeProduction.q_oil_t, NodeProduction.q_liquid_t, NodeProduction.q_water_m3, NodeProduction.q_gas_m3
        ).where(NodeProduction.node_id == node_id, NodeProduction.date == on_date)
    ).first()
    if row is None:
        return None
    return {"oil": row.q_oil_t, "liquid": row.q_liquid_t, "water": row.q_water_m3, "gas": row.q_gas_m3}


def _upsert_daily_production(
    session: Session, well_id: int, on_date: dt.date, out: WellAllocationOutput, source: str
) -> None:
    stmt = pg_insert(DailyProduction).values(
        well_id=well_id,
        date=on_date,
        q_oil_t=out.allocated["oil"],
        q_liquid_t=out.allocated["liquid"],
        q_water_m3=out.allocated["water"],
        q_gas_m3=out.allocated.get("gas"),
        hours_on=round(out.ke * 24, 2),
        ke=round(out.ke, 4),
        allocation_factor=out.allocation_factor,
        allocation_method=out.allocation_method,
        confidence=out.confidence,
        source=source,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyProduction.well_id, DailyProduction.date],
        set_={
            "q_oil_t": stmt.excluded.q_oil_t,
            "q_liquid_t": stmt.excluded.q_liquid_t,
            "q_water_m3": stmt.excluded.q_water_m3,
            "q_gas_m3": stmt.excluded.q_gas_m3,
            "hours_on": stmt.excluded.hours_on,
            "ke": stmt.excluded.ke,
            "allocation_factor": stmt.excluded.allocation_factor,
            "allocation_method": stmt.excluded.allocation_method,
            "confidence": stmt.excluded.confidence,
            "source": stmt.excluded.source,
        },
    )
    session.execute(stmt)


def run_period(
    session: Session,
    period: Period,
    node_ids: list[int] | None = None,
    raw_config: dict | None = None,
    source: str = "allocation",
) -> AllocationReport:
    raw_config = raw_config or load_raw_config()

    node_query = select(GatheringNode.id, GatheringNode.field_id)
    if node_ids:
        node_query = node_query.where(GatheringNode.id.in_(node_ids))
    nodes = session.execute(node_query).all()

    current_tag_id = session.execute(
        select(MeasurementTag.id).where(MeasurementTag.code == "esp_current_a")
    ).scalar_one_or_none()
    hours_tag_id = session.execute(
        select(MeasurementTag.id).where(MeasurementTag.code == "hours_on_daily")
    ).scalar_one_or_none()

    total_well_days = 0
    allocated_well_days = 0
    no_node_data_days = 0
    method_counts: dict[str, int] = defaultdict(int)
    warnings_count: dict[str, int] = defaultdict(int)

    for node_id, field_id in nodes:
        cfg = resolve_config(raw_config, field_id=field_id)

        current_date = period.start
        while current_date <= period.end:
            well_ids = _active_wells(session, node_id, current_date)
            if not well_ids:
                current_date += dt.timedelta(days=1)
                continue

            total_well_days += len(well_ids)

            node_fact = _node_fact(session, node_id, current_date)
            if node_fact is None:
                no_node_data_days += 1
                current_date += dt.timedelta(days=1)
                continue

            well_inputs: list[WellDayInput] = []
            for well_id in well_ids:
                valid_tests = _valid_tests_up_to(session, well_id, current_date)
                analog = (
                    _analog_candidates(session, well_id, current_date, cfg["analog"]["max_age_days"])
                    if not valid_tests
                    else []
                )
                resolved = resolve_well_rates(well_id, valid_tests, current_date, analog, cfg)
                if resolved is None:
                    continue  # совсем нечем аллоцировать — ни замеров, ни аналогов

                telemetry_hd = _telemetry_hours_down(
                    session, current_tag_id, well_id, current_date, cfg["ke"]["current_threshold_a"]
                )
                downtime_hd = _downtime_hours(session, well_id, current_date)
                rapport_ho = _rapport_hours_on(session, hours_tag_id, well_id, current_date)
                ke, ke_source = resolve_ke(telemetry_hd, downtime_hd, rapport_ho)

                well_inputs.append(WellDayInput(well_id=well_id, rates=resolved, ke=ke, ke_source=ke_source))

            for out in allocate_node_day(well_inputs, node_fact, cfg["k_bounds"]):
                _upsert_daily_production(session, out.well_id, current_date, out, source)
                allocated_well_days += 1
                method_counts[out.allocation_method] += 1
                for w in out.warnings:
                    warnings_count[w] += 1

            current_date += dt.timedelta(days=1)

    session.flush()

    return AllocationReport(
        period_start=period.start,
        period_end=period.end,
        total_well_days=total_well_days,
        allocated_well_days=allocated_well_days,
        no_node_data_days=no_node_data_days,
        method_counts=dict(method_counts),
        warnings_count=dict(warnings_count),
    )
