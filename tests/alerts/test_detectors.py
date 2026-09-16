"""По сценарию на детектор: явно срабатывает / явно не срабатывает."""

import datetime as dt

from src.alerts.detectors import (
    DataGapDetector,
    GorRiseDetector,
    MtbfApproachDetector,
    PressureAnomalyDetector,
    ProductionDropDetector,
    StaleTestDetector,
    WaterCutRiseDetector,
    WellStoppedDetector,
)
from src.domain.master_data import Equipment
from src.domain.timeseries import DailyProduction, Measurement, WellTest
from src.ingestion.base import Period

TAG_CURRENT = 3
TAG_P_BUF = 1

END = dt.date(2024, 6, 15)
PERIOD = Period(END, END)


def _ts(hour_offset_from_end_days: int = 0, hour: int = 12) -> dt.datetime:
    return dt.datetime.combine(END - dt.timedelta(days=hour_offset_from_end_days), dt.time(hour), tzinfo=dt.timezone.utc)


def _well_test(well_id, days_before_end, q_oil=30.0, q_liquid=40.0, water_cut=25.0, gor=50.0, **kwargs):
    ts_start = _ts(days_before_end, 8)
    defaults = dict(
        well_id=well_id, ts_start=ts_start, ts_end=ts_start + dt.timedelta(hours=4), duration_h=4.0,
        q_liquid=q_liquid, q_oil=q_oil, q_water=q_liquid - q_oil, water_cut=water_cut, gor=gor,
        is_valid=True, method="agzu",
    )
    defaults.update(kwargs)
    return WellTest(**defaults)


def test_well_stopped_detector_fires_on_sustained_low_current(db_session, make_well):
    well = make_well()
    # окно проверки — последние 6 ч до конца суток (as_of = конец END), поэтому
    # точки замера должны быть ближе к концу дня, а не к полудню
    for hour in (18, 20, 22):
        db_session.add(Measurement(well_id=well.id, ts=_ts(0, hour), tag_id=TAG_CURRENT, value=1.0, quality="good", source="test"))
    db_session.flush()

    alerts = WellStoppedDetector().check(db_session, PERIOD)
    assert any(a.well_id == well.id for a in alerts)


def test_well_stopped_detector_silent_when_current_normal(db_session, make_well):
    well = make_well()
    for hour in (18, 20, 22):
        db_session.add(Measurement(well_id=well.id, ts=_ts(0, hour), tag_id=TAG_CURRENT, value=30.0, quality="good", source="test"))
    db_session.flush()

    alerts = WellStoppedDetector().check(db_session, PERIOD)
    assert not any(a.well_id == well.id for a in alerts)


def test_water_cut_rise_detector_fires_on_big_jump(db_session, make_well):
    well = make_well()
    db_session.add(_well_test(well.id, days_before_end=40, water_cut=20.0))
    db_session.add(_well_test(well.id, days_before_end=1, water_cut=45.0))
    db_session.flush()

    alerts = WaterCutRiseDetector().check(db_session, PERIOD)
    assert any(a.well_id == well.id for a in alerts)


def test_water_cut_rise_detector_silent_on_small_change(db_session, make_well):
    well = make_well()
    db_session.add(_well_test(well.id, days_before_end=40, water_cut=20.0))
    db_session.add(_well_test(well.id, days_before_end=1, water_cut=25.0))
    db_session.flush()

    alerts = WaterCutRiseDetector().check(db_session, PERIOD)
    assert not any(a.well_id == well.id for a in alerts)


def test_gor_rise_detector_fires_on_big_jump(db_session, make_well):
    well = make_well()
    db_session.add(_well_test(well.id, days_before_end=40, gor=40.0))
    db_session.add(_well_test(well.id, days_before_end=1, gor=100.0))
    db_session.flush()

    alerts = GorRiseDetector().check(db_session, PERIOD)
    assert any(a.well_id == well.id for a in alerts)


def test_pressure_anomaly_detector_fires_on_outlier(db_session, make_well):
    well = make_well()
    for i in range(20):
        db_session.add(
            Measurement(well_id=well.id, ts=_ts(i, 12), tag_id=TAG_P_BUF, value=15.0 + (0.1 if i % 2 else -0.1), quality="good", source="test")
        )
    db_session.add(Measurement(well_id=well.id, ts=_ts(0, 13), tag_id=TAG_P_BUF, value=40.0, quality="good", source="test"))
    db_session.flush()

    alerts = PressureAnomalyDetector().check(db_session, PERIOD)
    assert any(a.well_id == well.id for a in alerts)


def test_pressure_anomaly_detector_silent_on_stable_pressure(db_session, make_well):
    well = make_well()
    for i in range(20):
        db_session.add(
            Measurement(well_id=well.id, ts=_ts(i, 12), tag_id=TAG_P_BUF, value=15.0 + (0.1 if i % 2 else -0.1), quality="good", source="test")
        )
    db_session.flush()

    alerts = PressureAnomalyDetector().check(db_session, PERIOD)
    assert not any(a.well_id == well.id for a in alerts)


def test_stale_test_detector_fires_when_overdue(db_session, make_well):
    well = make_well()
    db_session.add(_well_test(well.id, days_before_end=20))
    db_session.flush()

    alerts = StaleTestDetector().check(db_session, PERIOD)
    assert any(a.well_id == well.id for a in alerts)


def test_stale_test_detector_silent_when_recent(db_session, make_well):
    well = make_well()
    db_session.add(_well_test(well.id, days_before_end=2))
    db_session.flush()

    alerts = StaleTestDetector().check(db_session, PERIOD)
    assert not any(a.well_id == well.id for a in alerts)


def test_mtbf_approach_detector_fires_near_expected_mtbf(db_session, make_well):
    well = make_well()
    db_session.add(
        Equipment(well_id=well.id, equipment_type="esp", install_date=END - dt.timedelta(days=500), pull_date=None)
    )
    db_session.flush()

    alerts = MtbfApproachDetector().check(db_session, PERIOD)
    assert any(a.well_id == well.id for a in alerts)


def test_mtbf_approach_detector_silent_for_fresh_pump(db_session, make_well):
    well = make_well()
    db_session.add(
        Equipment(well_id=well.id, equipment_type="esp", install_date=END - dt.timedelta(days=30), pull_date=None)
    )
    db_session.flush()

    alerts = MtbfApproachDetector().check(db_session, PERIOD)
    assert not any(a.well_id == well.id for a in alerts)


def test_production_drop_detector_fires_when_actual_far_below_potential(db_session, make_well):
    well = make_well()
    db_session.add(_well_test(well.id, days_before_end=2, q_oil=40.0, q_liquid=50.0))
    db_session.add(
        DailyProduction(
            well_id=well.id, date=END, q_oil_t=10.0, q_liquid_t=15.0, q_water_m3=5.0,
            hours_on=24.0, ke=1.0, source="test",
        )
    )
    db_session.flush()

    alerts = ProductionDropDetector().check(db_session, PERIOD)
    assert any(a.well_id == well.id for a in alerts)


def test_production_drop_detector_silent_when_on_target(db_session, make_well):
    well = make_well()
    db_session.add(_well_test(well.id, days_before_end=2, q_oil=40.0, q_liquid=50.0))
    db_session.add(
        DailyProduction(
            well_id=well.id, date=END, q_oil_t=39.0, q_liquid_t=49.0, q_water_m3=10.0,
            hours_on=24.0, ke=1.0, source="test",
        )
    )
    db_session.flush()

    alerts = ProductionDropDetector().check(db_session, PERIOD)
    assert not any(a.well_id == well.id for a in alerts)


def test_data_gap_detector_fires_on_long_silence(db_session, make_well):
    well = make_well()
    db_session.add(Measurement(well_id=well.id, ts=_ts(2, 12), tag_id=TAG_CURRENT, value=30.0, quality="good", source="test"))
    db_session.flush()

    alerts = DataGapDetector().check(db_session, PERIOD)
    assert any(a.well_id == well.id for a in alerts)


def test_data_gap_detector_silent_on_recent_telemetry(db_session, make_well):
    well = make_well()
    db_session.add(Measurement(well_id=well.id, ts=_ts(0, 22), tag_id=TAG_CURRENT, value=30.0, quality="good", source="test"))
    db_session.flush()

    alerts = DataGapDetector().check(db_session, PERIOD)
    assert not any(a.well_id == well.id for a in alerts)
