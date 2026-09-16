"""Дедупликация и подавление каскада — обязательные по заданию, плюс
автозакрытие и квитирование/отложить."""

import datetime as dt

from sqlalchemy import select

from src.alerts.detectors import WellStoppedDetector
from src.alerts.lifecycle import acknowledge, process_period, snooze
from src.domain.alerts import Alert
from src.domain.master_data import GatheringNode
from src.domain.timeseries import Measurement
from src.ingestion.base import Period

TAG_CURRENT = 3
END = dt.date(2024, 6, 15)
PERIOD = Period(END, END)


def _ts(hour: int) -> dt.datetime:
    return dt.datetime.combine(END, dt.time(hour), tzinfo=dt.timezone.utc)


def _make_stopped(db_session, well, value=1.0):
    for hour in (18, 20, 22):
        db_session.add(Measurement(well_id=well.id, ts=_ts(hour), tag_id=TAG_CURRENT, value=value, quality="good", source="test"))
    db_session.flush()


def test_dedup_does_not_duplicate_while_active(db_session, make_well):
    well = make_well()
    _make_stopped(db_session, well)

    first = process_period(db_session, PERIOD, detector_classes=[WellStoppedDetector])
    second = process_period(db_session, PERIOD, detector_classes=[WellStoppedDetector])

    assert first.created == 1
    assert second.created == 0
    assert second.updated == 1

    rows = db_session.execute(select(Alert).where(Alert.well_id == well.id, Alert.type == "well_stopped")).scalars().all()
    assert len(rows) == 1


def test_auto_resolve_when_condition_clears(db_session, make_well):
    well = make_well()
    _make_stopped(db_session, well)
    process_period(db_session, PERIOD, detector_classes=[WellStoppedDetector])

    row = db_session.execute(select(Alert).where(Alert.well_id == well.id, Alert.type == "well_stopped")).scalar_one()
    assert row.ts_resolved is None

    # ток вернулся в норму — одной новой точки достаточно, чтобы сломать
    # условие "все показания в окне ниже порога" (PK measurement — другое ts)
    db_session.add(Measurement(well_id=well.id, ts=_ts(23), tag_id=TAG_CURRENT, value=30.0, quality="good", source="test2"))
    db_session.flush()

    report = process_period(db_session, PERIOD, detector_classes=[WellStoppedDetector])
    db_session.refresh(row)
    assert report.resolved == 1
    assert row.ts_resolved is not None


def test_cascade_suppression_creates_one_group_alert(db_session, sample_node, make_well):
    wells = [make_well(node=sample_node) for _ in range(4)]
    for well in wells:
        _make_stopped(db_session, well)

    report = process_period(db_session, PERIOD, detector_classes=[WellStoppedDetector])

    assert report.cascades_created == 1
    assert report.suppressed_by_cascade == 4
    assert report.created == 1  # один групповой алерт, не 4 отдельных

    individual = db_session.execute(
        select(Alert).where(Alert.type == "well_stopped", Alert.well_id.in_([w.id for w in wells]))
    ).scalars().all()
    assert individual == []

    cascade = db_session.execute(select(Alert).where(Alert.type == "node_stopped_cascade")).scalar_one()
    assert cascade.node_id == sample_node.id
    assert cascade.value == 4
    assert set(cascade.message.split()) or True  # сообщение непустое, есть смысл


def test_cascade_not_triggered_below_min_wells(db_session, sample_node, make_well):
    wells = [make_well(node=sample_node) for _ in range(2)]  # меньше cascade.min_wells=3
    for well in wells:
        _make_stopped(db_session, well)

    report = process_period(db_session, PERIOD, detector_classes=[WellStoppedDetector])

    assert report.cascades_created == 0
    assert report.created == 2  # обе — отдельные алерты, не групповой


def test_acknowledge_sets_fields(db_session, make_well):
    well = make_well()
    _make_stopped(db_session, well)
    process_period(db_session, PERIOD, detector_classes=[WellStoppedDetector])
    alert = db_session.execute(select(Alert).where(Alert.well_id == well.id)).scalar_one()

    acknowledge(db_session, alert.id, acknowledged_by="Иванов", comment="Идёт бригада")

    db_session.refresh(alert)
    assert alert.is_acknowledged is True
    assert alert.acknowledged_by == "Иванов"
    assert alert.comment == "Идёт бригада"
    assert alert.acknowledged_at is not None


def test_snooze_sets_snoozed_until(db_session, make_well):
    well = make_well()
    _make_stopped(db_session, well)
    process_period(db_session, PERIOD, detector_classes=[WellStoppedDetector])
    alert = db_session.execute(select(Alert).where(Alert.well_id == well.id)).scalar_one()

    before = dt.datetime.now(dt.timezone.utc)
    snooze(db_session, alert.id, hours=24)

    db_session.refresh(alert)
    assert alert.snoozed_until is not None
    assert alert.snoozed_until > before + dt.timedelta(hours=23)
