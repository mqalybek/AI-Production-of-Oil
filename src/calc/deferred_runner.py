"""Сборка входных данных для расчёта потерь из БД + batch-прогон по периоду +
upsert в deferred_production + агрегация/Парето поверх неё.

Чистая математика — в src/calc/deferred.py. Как и в validation_runner.py и
allocation_runner.py — запросы по (скважина, дата) без агрессивной
батчировки, для периодического batch-прогона этого достаточно.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.calc.deferred import (
    DeferredLossLine,
    DowntimeInterval,
    ProductionPoint,
    compute_day_losses,
    compute_idle_fund_loss,
    load_raw_config,
    pick_primary_potential,
    potential_from_decline_trend,
    potential_from_last_valid_test,
    potential_from_model_forecast,
    resolve_config,
)
from src.domain.master_data import Completion, Well, WellGatheringNodeHistory
from src.domain.timeseries import DailyProduction, DeferredProduction, Downtime, WellTest
from src.ingestion.base import Period


@dataclass
class DeferredReport:
    period_start: dt.date
    period_end: dt.date
    well_days_processed: int
    total_loss_oil_t: float
    by_category: dict[str, float] = field(default_factory=dict)
    basis_counts: dict[str, int] = field(default_factory=dict)


# --- сборка входных данных ------------------------------------------------------


def _last_valid_test(session: Session, well_id: int, on_date: dt.date) -> WellTest | None:
    upper = dt.datetime.combine(on_date, dt.time.max, tzinfo=dt.timezone.utc)
    return session.execute(
        select(WellTest)
        .where(WellTest.well_id == well_id, WellTest.is_valid.is_(True), WellTest.ts_start <= upper)
        .order_by(WellTest.ts_start.desc())
    ).scalars().first()


def _production_history(session: Session, well_id: int, on_date: dt.date, months: int) -> list[ProductionPoint]:
    lower = on_date - dt.timedelta(days=months * 30)
    rows = session.execute(
        select(DailyProduction.date, DailyProduction.q_oil_t, DailyProduction.q_liquid_t)
        .where(DailyProduction.well_id == well_id, DailyProduction.date >= lower, DailyProduction.date < on_date)
        .order_by(DailyProduction.date)
    ).all()
    return [ProductionPoint(date=r.date, q_oil=r.q_oil_t, q_liquid=r.q_liquid_t) for r in rows]


def _downtime_intervals(session: Session, well_id: int, on_date: dt.date) -> list[DowntimeInterval]:
    lower = dt.datetime.combine(on_date, dt.time.min, tzinfo=dt.timezone.utc)
    upper = dt.datetime.combine(on_date, dt.time.max, tzinfo=dt.timezone.utc)
    rows = session.execute(
        select(Downtime.reason_id, Downtime.ts_start, Downtime.ts_end).where(
            Downtime.well_id == well_id, Downtime.ts_start < upper, Downtime.ts_end > lower
        )
    ).all()
    by_reason: dict[int, float] = defaultdict(float)
    for reason_id, ts_start, ts_end in rows:
        overlap_hours = (min(ts_end, upper) - max(ts_start, lower)).total_seconds() / 3600
        by_reason[reason_id] += max(0.0, overlap_hours)
    return [DowntimeInterval(reason_id=r, hours=min(24.0, h)) for r, h in by_reason.items()]


def _resolve_potential(session: Session, well_id: int, on_date: dt.date, cfg: dict):
    last_test = _last_valid_test(session, well_id, on_date)
    pot_last = potential_from_last_valid_test(last_test)

    history = _production_history(session, well_id, on_date, cfg["decline_trend"]["history_months"])
    pot_decline = potential_from_decline_trend(history, on_date, cfg)

    pot_model = potential_from_model_forecast(well_id, on_date)

    return pick_primary_potential(pot_model, pot_decline, pot_last)


def _well_day_losses(session: Session, well_id: int, on_date: dt.date, cfg: dict) -> list[DeferredLossLine]:
    potential = _resolve_potential(session, well_id, on_date, cfg)
    if potential is None:
        return []

    dp = session.execute(
        select(DailyProduction).where(DailyProduction.well_id == well_id, DailyProduction.date == on_date)
    ).scalar_one_or_none()

    hours_on = dp.hours_on if dp else 0.0
    q_oil_actual = dp.q_oil_t if dp else 0.0
    q_liquid_actual = dp.q_liquid_t if dp else 0.0

    downtime = _downtime_intervals(session, well_id, on_date)
    return compute_day_losses(potential, hours_on, q_oil_actual, q_liquid_actual, downtime)


def _idle_fund_losses(session: Session, well_id: int, on_date: dt.date, cfg: dict) -> list[DeferredLossLine]:
    last_test = _last_valid_test(session, well_id, on_date)
    if last_test is None:
        return []
    age_days = (on_date - last_test.ts_start.date()).days
    if age_days > cfg["idle_fund"]["max_potential_age_days"]:
        return []
    potential = potential_from_last_valid_test(last_test)
    return [compute_idle_fund_loss(potential)]


# --- upsert -----------------------------------------------------------------------


def _upsert_line(session: Session, well_id: int, on_date: dt.date, line: DeferredLossLine) -> None:
    values = dict(
        well_id=well_id,
        date=on_date,
        category=line.category,
        reason_id=line.reason_id,
        volume_oil_t=line.volume_oil_t,
        potential_basis=line.potential_basis,
    )
    stmt = pg_insert(DeferredProduction).values(**values)
    if line.reason_id is not None:
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                DeferredProduction.well_id,
                DeferredProduction.date,
                DeferredProduction.category,
                DeferredProduction.reason_id,
            ],
            index_where=DeferredProduction.reason_id.is_not(None),
            set_={"volume_oil_t": stmt.excluded.volume_oil_t, "potential_basis": stmt.excluded.potential_basis},
        )
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=[DeferredProduction.well_id, DeferredProduction.date, DeferredProduction.category],
            index_where=DeferredProduction.reason_id.is_(None),
            set_={"volume_oil_t": stmt.excluded.volume_oil_t, "potential_basis": stmt.excluded.potential_basis},
        )
    session.execute(stmt)


# --- batch-прогон -------------------------------------------------------------------


def run_period(
    session: Session, period: Period, well_ids: list[int] | None = None, raw_config: dict | None = None
) -> DeferredReport:
    raw_config = raw_config or load_raw_config()

    well_query = select(Well.id, Well.field_id, Well.status).where(Well.well_type == "producer")
    if well_ids:
        well_query = well_query.where(Well.id.in_(well_ids))
    wells = session.execute(well_query).all()

    well_days_processed = 0
    total_loss = 0.0
    by_category: dict[str, float] = defaultdict(float)
    basis_counts: dict[str, int] = defaultdict(int)

    for well_id, field_id, status in wells:
        cfg = resolve_config(raw_config, field_id=field_id, well_id=well_id)
        is_idle = status in cfg["idle_fund"]["statuses"]

        current_date = period.start
        while current_date <= period.end:
            lines = (
                _idle_fund_losses(session, well_id, current_date, cfg)
                if is_idle
                else _well_day_losses(session, well_id, current_date, cfg)
            )

            for line in lines:
                _upsert_line(session, well_id, current_date, line)
                total_loss += line.volume_oil_t
                by_category[line.category] += line.volume_oil_t
                basis_counts[line.potential_basis] += 1
                well_days_processed += 1

            current_date += dt.timedelta(days=1)

    session.flush()

    return DeferredReport(
        period_start=period.start,
        period_end=period.end,
        well_days_processed=well_days_processed,
        total_loss_oil_t=round(total_loss, 2),
        by_category={k: round(v, 2) for k, v in by_category.items()},
        basis_counts=dict(basis_counts),
    )


# --- агрегация и Парето -----------------------------------------------------------


def _well_dimension_maps(session: Session, well_ids: list[int], as_of: dt.date) -> dict[str, dict[int, int | None]]:
    field_map = {
        w.id: w.field_id for w in session.execute(select(Well.id, Well.field_id).where(Well.id.in_(well_ids))).all()
    }

    node_map: dict[int, int | None] = {}
    for row in session.execute(
        select(WellGatheringNodeHistory.well_id, WellGatheringNodeHistory.node_id).where(
            WellGatheringNodeHistory.well_id.in_(well_ids),
            WellGatheringNodeHistory.valid_from <= as_of,
            (WellGatheringNodeHistory.valid_to.is_(None)) | (WellGatheringNodeHistory.valid_to > as_of),
        )
    ).all():
        node_map[row.well_id] = row.node_id

    reservoir_map: dict[int, int | None] = {}
    for row in session.execute(
        select(Completion.well_id, Completion.reservoir_id).where(Completion.well_id.in_(well_ids))
    ).all():
        reservoir_map.setdefault(row.well_id, row.reservoir_id)

    return {"field": field_map, "node": node_map, "reservoir": reservoir_map}


def _bucket_date(d: dt.date, time_bucket: str | None) -> dt.date:
    if time_bucket is None or time_bucket == "day":
        return d
    if time_bucket == "week":
        return d - dt.timedelta(days=d.weekday())
    if time_bucket == "month":
        return d.replace(day=1)
    if time_bucket == "ytd":
        return dt.date(d.year, 1, 1)
    raise ValueError(f"неизвестный time_bucket: {time_bucket!r} (day/week/month/ytd)")


def aggregate_losses(
    session: Session,
    period: Period,
    group_by: str = "well",
    time_bucket: str | None = "day",
    well_ids: list[int] | None = None,
) -> list[dict]:
    """group_by: 'well' | 'node' (= куст, отдельной сущности в схеме нет) |
    'reservoir' (объект) | 'field' (месторождение). time_bucket: 'day' |
    'week' | 'month' | 'ytd' | None (без разбивки по времени)."""
    if group_by not in ("well", "node", "reservoir", "field"):
        raise ValueError(f"неизвестный group_by: {group_by!r}")

    q = select(
        DeferredProduction.well_id,
        DeferredProduction.date,
        DeferredProduction.category,
        func.sum(DeferredProduction.volume_oil_t).label("total"),
    ).where(DeferredProduction.date.between(period.start, period.end))
    if well_ids:
        q = q.where(DeferredProduction.well_id.in_(well_ids))
    q = q.group_by(DeferredProduction.well_id, DeferredProduction.date, DeferredProduction.category)

    rows = session.execute(q).all()
    if not rows:
        return []

    dims = (
        _well_dimension_maps(session, sorted({r.well_id for r in rows}), period.end)
        if group_by != "well"
        else {}
    )

    def _group_key(well_id: int) -> int | None:
        return well_id if group_by == "well" else dims[group_by].get(well_id)

    totals: dict[tuple, float] = defaultdict(float)
    for r in rows:
        key = (_group_key(r.well_id), _bucket_date(r.date, time_bucket), r.category)
        totals[key] += r.total

    return [
        {"group": g, "period": p, "category": c, "volume_oil_t": round(v, 2)}
        for (g, p, c), v in sorted(totals.items(), key=lambda kv: (kv[0][1] or dt.date.min, kv[0][0] or 0, kv[0][2]))
    ]


def pareto_by_reason(session: Session, period: Period, well_ids: list[int] | None = None) -> list[dict]:
    """Парето по причинам потерь: category + reason_id, отсортировано по
    убыванию объёма, с накопленной долей."""
    q = select(
        DeferredProduction.category,
        DeferredProduction.reason_id,
        func.sum(DeferredProduction.volume_oil_t).label("total"),
    ).where(DeferredProduction.date.between(period.start, period.end))
    if well_ids:
        q = q.where(DeferredProduction.well_id.in_(well_ids))
    q = q.group_by(DeferredProduction.category, DeferredProduction.reason_id).order_by(
        func.sum(DeferredProduction.volume_oil_t).desc()
    )

    rows = session.execute(q).all()
    grand_total = sum(r.total for r in rows) or 1.0

    result = []
    cumulative = 0.0
    for r in rows:
        cumulative += r.total
        result.append(
            {
                "category": r.category,
                "reason_id": r.reason_id,
                "volume_oil_t": round(r.total, 2),
                "share_pct": round(100 * r.total / grand_total, 1),
                "cumulative_pct": round(100 * cumulative / grand_total, 1),
            }
        )
    return result
