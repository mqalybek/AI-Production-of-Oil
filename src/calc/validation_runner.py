"""Сборка RuleContext из БД + batch-прогон валидации по периоду + отчёт о
качестве данных (для дашборда). Всё, что обращается к БД, живёт здесь —
src/calc/validation.py остаётся чистым и тестируется без сессии.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.calc.validation import EventInfo, RuleContext, RunResult, evaluate, load_raw_config, resolve_config
from src.domain.master_data import Equipment, GatheringNode, Well, WellGatheringNodeHistory
from src.domain.reference import MeasurementTag
from src.domain.timeseries import Downtime, GtmEvent, Measurement, NodeProduction, WellTest
from src.ingestion.base import Period


@dataclass
class RuleStats:
    failed: int
    total: int
    fail_rate: float


@dataclass
class ValidationReport:
    period_start: dt.date
    period_end: dt.date
    total_tests: int
    valid_tests: int
    invalid_tests: int
    warning_tests: int  # is_valid=True, но есть хотя бы один warning
    by_rule: dict[str, RuleStats] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-совместимый вид — для API/дашборда метрики качества данных."""
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_tests": self.total_tests,
            "valid_tests": self.valid_tests,
            "invalid_tests": self.invalid_tests,
            "warning_tests": self.warning_tests,
            "reject_rate": round(self.invalid_tests / self.total_tests, 4) if self.total_tests else 0.0,
            "by_rule": {
                rule: {"failed": s.failed, "total": s.total, "fail_rate": s.fail_rate}
                for rule, s in self.by_rule.items()
            },
        }


def _wells_nodes(session: Session, well_ids: list[int], as_of: dt.date) -> dict[int, tuple[int | None, str | None]]:
    rows = session.execute(
        select(WellGatheringNodeHistory.well_id, WellGatheringNodeHistory.node_id, GatheringNode.node_type)
        .join(GatheringNode, GatheringNode.id == WellGatheringNodeHistory.node_id)
        .where(
            WellGatheringNodeHistory.well_id.in_(well_ids),
            WellGatheringNodeHistory.valid_from <= as_of,
            (WellGatheringNodeHistory.valid_to.is_(None)) | (WellGatheringNodeHistory.valid_to > as_of),
        )
    ).all()
    result: dict[int, tuple[int | None, str | None]] = {w: (None, None) for w in well_ids}
    for well_id, node_id, node_type in rows:
        result[well_id] = (node_id, node_type)
    return result


def _load_events(session: Session, well_id: int, start_dt: dt.datetime, end_dt: dt.datetime) -> list[EventInfo]:
    events: list[EventInfo] = []

    for ev in session.execute(
        select(GtmEvent).where(
            GtmEvent.well_id == well_id, GtmEvent.event_date.between(start_dt.date(), end_dt.date())
        )
    ).scalars():
        at = dt.datetime.combine(ev.event_date, dt.time.min, tzinfo=dt.timezone.utc)
        events.append(EventInfo(kind="gtm", at=at, description=ev.description or "ГТМ"))

    for eq in session.execute(
        select(Equipment).where(
            Equipment.well_id == well_id, Equipment.install_date.between(start_dt.date(), end_dt.date())
        )
    ).scalars():
        at = dt.datetime.combine(eq.install_date, dt.time.min, tzinfo=dt.timezone.utc)
        events.append(EventInfo(kind="pump_change", at=at, description="Смена насоса"))

    for downtime in session.execute(
        select(Downtime).where(Downtime.well_id == well_id, Downtime.ts_end.between(start_dt, end_dt))
    ).scalars():
        events.append(EventInfo(kind="downtime_end", at=downtime.ts_end, description="выход из простоя"))

    return events


def _telemetry_current(
    session: Session, current_tag_id: int | None, well_id: int, ts_start: dt.datetime, ts_end: dt.datetime
) -> list[float] | None:
    if current_tag_id is None:
        return None
    values = list(
        session.execute(
            select(Measurement.value).where(
                Measurement.well_id == well_id,
                Measurement.tag_id == current_tag_id,
                Measurement.ts >= ts_start,
                Measurement.ts <= ts_end,
            )
        ).scalars()
    )
    return values or None


def _node_fact(session: Session, node_id: int | None, on_date: dt.date) -> dict | None:
    if node_id is None:
        return None
    row = session.execute(
        select(NodeProduction.q_liquid_t, NodeProduction.q_oil_t).where(
            NodeProduction.node_id == node_id, NodeProduction.date == on_date
        )
    ).first()
    if row is None:
        return None
    return {"q_liquid_t": row.q_liquid_t, "q_oil_t": row.q_oil_t}


def run_period(
    session: Session,
    period: Period,
    well_ids: list[int] | None = None,
    raw_config: dict | None = None,
    lookback_days: int = 60,
    persist: bool = False,
) -> ValidationReport:
    """Валидирует все well_test за период (для скважин well_ids или всех
    добывающих). persist=True — записывает test.is_valid/validation_flags и
    флашит сессию (коммит — на вызывающей стороне)."""

    raw_config = raw_config or load_raw_config()

    well_query = select(Well.id, Well.field_id).where(Well.well_type == "producer")
    if well_ids:
        well_query = well_query.where(Well.id.in_(well_ids))
    wells = session.execute(well_query).all()
    well_field = {w.id: w.field_id for w in wells}
    all_well_ids = list(well_field)
    if not all_well_ids:
        return ValidationReport(period.start, period.end, 0, 0, 0, 0, {})

    well_node = _wells_nodes(session, all_well_ids, period.end)

    period_start_dt = dt.datetime.combine(period.start, dt.time.min, tzinfo=dt.timezone.utc)
    period_end_dt = dt.datetime.combine(period.end, dt.time.max, tzinfo=dt.timezone.utc)
    lookback_dt = period_start_dt - dt.timedelta(days=lookback_days)

    current_tag_id = session.execute(
        select(MeasurementTag.id).where(MeasurementTag.code == "esp_current_a")
    ).scalar_one_or_none()

    # группировка тестов периода по (узел, дата) — для material_balance
    period_tests = session.execute(
        select(WellTest).where(
            WellTest.well_id.in_(all_well_ids), WellTest.ts_start.between(period_start_dt, period_end_dt)
        )
    ).scalars().all()
    node_date_tests: dict[tuple[int, dt.date], list[WellTest]] = defaultdict(list)
    for t in period_tests:
        node_id, _ = well_node.get(t.well_id, (None, None))
        if node_id is not None:
            node_date_tests[(node_id, t.ts_start.date())].append(t)
    node_fact_cache: dict[tuple[int, dt.date], dict | None] = {}

    all_results: list[tuple[WellTest, RunResult]] = []
    by_rule_failed: dict[str, int] = defaultdict(int)
    by_rule_total: dict[str, int] = defaultdict(int)

    for well_id, field_id in well_field.items():
        node_id, node_type = well_node.get(well_id, (None, None))

        tests = session.execute(
            select(WellTest)
            .where(WellTest.well_id == well_id, WellTest.ts_start.between(lookback_dt, period_end_dt))
            .order_by(WellTest.ts_start)
        ).scalars().all()

        events = _load_events(session, well_id, lookback_dt, period_end_dt)
        cfg = resolve_config(raw_config, field_id=field_id, well_id=well_id, node_type=node_type)
        rolling_window = cfg["gor_anomaly"]["rolling_window_tests"]

        previous_valid: WellTest | None = None
        gor_history: list[float] = []

        for test in tests:
            in_period = period_start_dt <= test.ts_start <= period_end_dt

            if in_period:
                sibling_tests = [
                    t for t in node_date_tests.get((node_id, test.ts_start.date()), []) if t.id != test.id
                ] if node_id is not None else []

                cache_key = (node_id, test.ts_start.date())
                if cache_key not in node_fact_cache:
                    node_fact_cache[cache_key] = _node_fact(session, node_id, test.ts_start.date())

                context = RuleContext(
                    config=cfg,
                    previous_valid_test=previous_valid,
                    events=events,
                    gor_history=list(gor_history),
                    sibling_tests=sibling_tests,
                    node_fact=node_fact_cache[cache_key],
                    telemetry_current=_telemetry_current(
                        session, current_tag_id, well_id, test.ts_start, test.ts_end
                    ),
                )
                result = evaluate(test, context)
                all_results.append((test, result))

                for r in result.results:
                    by_rule_total[r.rule] += 1
                    if not r.passed:
                        by_rule_failed[r.rule] += 1

                if persist:
                    test.is_valid = result.is_valid
                    test.validation_flags = result.validation_flags

                test_is_valid = result.is_valid
            else:
                # тест до начала периода — только контекст для следующих, не оцениваем
                test_is_valid = bool(test.is_valid)

            if test_is_valid:
                previous_valid = test
                if test.gor is not None:
                    gor_history = (gor_history + [test.gor])[-rolling_window:]

    if persist:
        session.flush()

    total = len(all_results)
    valid = sum(1 for _, r in all_results if r.is_valid)
    warning_only = sum(1 for _, r in all_results if r.is_valid and r.validation_flags["warnings"])

    by_rule = {
        rule: RuleStats(
            failed=by_rule_failed[rule],
            total=by_rule_total[rule],
            fail_rate=round(by_rule_failed[rule] / by_rule_total[rule], 4) if by_rule_total[rule] else 0.0,
        )
        for rule in by_rule_total
    }

    return ValidationReport(
        period_start=period.start,
        period_end=period.end,
        total_tests=total,
        valid_tests=valid,
        invalid_tests=total - valid,
        warning_tests=warning_only,
        by_rule=by_rule,
    )
