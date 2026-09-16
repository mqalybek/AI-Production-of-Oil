"""Тесты таймсерий: числовые примеры замеров/добычи + ограничения целостности."""

import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from src.domain.master_data import GatheringNode
from src.domain.reference import DowntimeReason, MeasurementTag
from src.domain.timeseries import DailyProduction, Downtime, Measurement, NodeProduction, WellTest


def _tz(hour: int, day: int = 1) -> dt.datetime:
    return dt.datetime(2024, 6, day, hour, 0, tzinfo=dt.timezone.utc)


def test_well_test_happy_path(db_session, sample_well):
    # 4-часовой замер на АГЗУ: Qж=48 м3/сут, обводнённость 25%, значит
    # Qн = 48 * (1 - 0.25) = 36 м3/сут (переводить в тонны — задача calc, не теста модели)
    test = WellTest(
        well_id=sample_well.id,
        ts_start=_tz(8),
        ts_end=_tz(12),
        duration_h=4.0,
        q_liquid=48.0,
        q_oil=36.0,
        q_water=12.0,
        q_gas=1500.0,
        water_cut=25.0,
        gor=41.7,
        p_buf=18.5,
        p_zatr=22.0,
        temperature=41.0,
        method="agzu",
        is_valid=True,
        operator="Иванов А.",
    )
    db_session.add(test)
    db_session.flush()
    assert test.id is not None


def test_well_test_period_must_be_positive(db_session, sample_well):
    db_session.add(
        WellTest(
            well_id=sample_well.id,
            ts_start=_tz(12),
            ts_end=_tz(8),  # конец раньше начала
            duration_h=4.0,
            q_liquid=48.0,
            q_oil=36.0,
            q_water=12.0,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("water_cut", [-1.0, 100.1])
def test_well_test_water_cut_must_be_within_0_100(db_session, sample_well, water_cut):
    db_session.add(
        WellTest(
            well_id=sample_well.id,
            ts_start=_tz(8),
            ts_end=_tz(12),
            duration_h=4.0,
            q_liquid=48.0,
            q_oil=36.0,
            q_water=12.0,
            water_cut=water_cut,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_daily_production_happy_path(db_session, sample_well):
    # скважина отработала 22.5 часа из 24, КЭ = 22.5 / 24 = 0.9375
    record = DailyProduction(
        well_id=sample_well.id,
        date=dt.date(2024, 6, 1),
        q_oil_t=18.4,
        q_liquid_t=24.6,
        q_water_m3=6.2,
        q_gas_m3=760.0,
        hours_on=22.5,
        ke=0.9375,
        allocation_factor=1.02,
        source="allocation",
    )
    db_session.add(record)
    db_session.flush()
    assert (sample_well.id, dt.date(2024, 6, 1)) == (record.well_id, record.date)


@pytest.mark.parametrize("hours_on", [-0.5, 24.5])
def test_daily_production_hours_on_range(db_session, sample_well, hours_on):
    db_session.add(
        DailyProduction(
            well_id=sample_well.id,
            date=dt.date(2024, 6, 1),
            q_oil_t=18.4,
            q_liquid_t=24.6,
            q_water_m3=6.2,
            hours_on=hours_on,
            ke=0.5,
            source="allocation",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_daily_production_negative_oil_rate_rejected(db_session, sample_well):
    db_session.add(
        DailyProduction(
            well_id=sample_well.id,
            date=dt.date(2024, 6, 1),
            q_oil_t=-1.0,
            q_liquid_t=24.6,
            q_water_m3=6.2,
            hours_on=24.0,
            ke=1.0,
            source="allocation",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_node_production_happy_path(db_session, sample_field):
    node = GatheringNode(field_id=sample_field.id, name="ГУ-1", node_type="gu")
    db_session.add(node)
    db_session.flush()

    db_session.add(
        NodeProduction(
            node_id=node.id,
            date=dt.date(2024, 6, 1),
            q_oil_t=340.0,
            q_liquid_t=510.0,
            q_water_m3=180.0,
            q_gas_m3=15300.0,
        )
    )
    db_session.flush()


def test_measurement_quality_must_be_known_value(db_session, sample_well):
    tag = MeasurementTag(code="p_zab", name="Давление забойное", unit="атм")
    db_session.add(tag)
    db_session.flush()

    db_session.add(
        Measurement(
            well_id=sample_well.id,
            ts=_tz(10),
            tag_id=tag.id,
            value=125.4,
            quality="unknown",  # не входит в ('good', 'suspect', 'bad')
            source="scada",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_downtime_requires_end_after_start(db_session, sample_well):
    reason = DowntimeReason(code="esp_failure", name="Отказ ЭЦН")
    db_session.add(reason)
    db_session.flush()

    db_session.add(
        Downtime(
            well_id=sample_well.id,
            ts_start=_tz(10),
            ts_end=_tz(10),  # нулевая длительность
            reason_id=reason.id,
            is_planned=False,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_downtime_happy_path_with_deferred_oil(db_session, sample_well):
    reason = DowntimeReason(code="no_power", name="Отсутствие электроэнергии")
    db_session.add(reason)
    db_session.flush()

    # простой 6 часов, потенциал 18.4 т/сут -> потери = 18.4 / 24 * 6 = 4.6 т
    downtime = Downtime(
        well_id=sample_well.id,
        ts_start=_tz(6),
        ts_end=_tz(12),
        reason_id=reason.id,
        comment="Отключение по сети 6 кВ",
        deferred_oil_t=4.6,
        is_planned=False,
    )
    db_session.add(downtime)
    db_session.flush()
    assert downtime.id is not None
