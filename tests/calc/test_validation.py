"""По 3+ кейса на правило: явно валидный, явно невалидный, граничный."""

import datetime as dt

from src.calc.validation import (
    EventInfo,
    RuleContext,
    duration_check,
    evaluate,
    gor_anomaly,
    load_raw_config,
    material_balance,
    physical_bounds,
    resolve_config,
    staleness,
    telemetry_consistency,
    water_cut_jump,
)
from src.calc.validation import deviation_from_previous as deviation_from_previous_rule
from src.domain.timeseries import WellTest

CFG = resolve_config(load_raw_config())


def _ts(day: int, hour: int = 8) -> dt.datetime:
    return dt.datetime(2024, 1, day, hour, tzinfo=dt.timezone.utc)


def make_test(**kwargs) -> WellTest:
    defaults = dict(
        well_id=1,
        ts_start=_ts(10),
        ts_end=_ts(10, 12),
        duration_h=4.0,
        q_liquid=50.0,
        q_oil=35.0,
        q_water=15.0,
        q_gas=1500.0,
        water_cut=30.0,
        gor=42.0,
        p_buf=15.0,
        p_zatr=18.0,
        temperature=40.0,
        method="agzu",
        is_valid=True,
        operator="test",
    )
    defaults.update(kwargs)
    return WellTest(**defaults)


def ctx(**kwargs) -> RuleContext:
    defaults: dict = dict(config=CFG)
    defaults.update(kwargs)
    return RuleContext(**defaults)


# --- duration_check -----------------------------------------------------------


def test_duration_check_valid():
    result = duration_check(make_test(duration_h=4.0), ctx())
    assert result.passed


def test_duration_check_invalid_too_short():
    result = duration_check(make_test(duration_h=0.5), ctx())
    assert not result.passed
    assert result.severity == "error"


def test_duration_check_boundary_exact_minimum():
    result = duration_check(make_test(duration_h=2.0), ctx())
    assert result.passed  # >= норматива


# --- physical_bounds ------------------------------------------------------------


def test_physical_bounds_valid():
    result = physical_bounds(make_test(), ctx())
    assert result.passed


def test_physical_bounds_invalid_water_cut_over_100():
    result = physical_bounds(make_test(water_cut=105.0), ctx())
    assert not result.passed
    assert "water_cut" in result.details["violations"]


def test_physical_bounds_boundary_water_cut_exactly_100():
    result = physical_bounds(make_test(water_cut=100.0), ctx())
    assert result.passed


def test_physical_bounds_invalid_negative_rate():
    result = physical_bounds(make_test(q_oil=-5.0), ctx())
    assert not result.passed
    assert "q_oil" in result.details["violations"]


# --- deviation_from_previous ------------------------------------------------------


def test_deviation_from_previous_valid_small_change():
    prev = make_test(ts_start=_ts(5), ts_end=_ts(5, 12), q_liquid=50.0)
    result = deviation_from_previous_rule(make_test(q_liquid=55.0), ctx(previous_valid_test=prev))
    assert result.passed


def test_deviation_from_previous_invalid_big_change_no_event():
    prev = make_test(ts_start=_ts(5), ts_end=_ts(5, 12), q_liquid=50.0)
    result = deviation_from_previous_rule(make_test(q_liquid=80.0), ctx(previous_valid_test=prev))
    assert not result.passed


def test_deviation_from_previous_boundary_exact_threshold():
    prev = make_test(ts_start=_ts(5), ts_end=_ts(5, 12), q_liquid=100.0)
    result = deviation_from_previous_rule(make_test(q_liquid=130.0), ctx(previous_valid_test=prev))  # 30%
    assert result.passed


def test_deviation_from_previous_explained_by_gtm():
    prev = make_test(ts_start=_ts(5), ts_end=_ts(5, 12), q_liquid=50.0)
    event = EventInfo(kind="gtm", at=_ts(9), description="ГРП 09.01")
    result = deviation_from_previous_rule(
        make_test(q_liquid=80.0), ctx(previous_valid_test=prev, events=[event])
    )
    assert result.passed
    assert result.details["explained_by"] == "gtm"


# --- water_cut_jump ---------------------------------------------------------------


def test_water_cut_jump_valid_small():
    prev = make_test(ts_start=_ts(5), ts_end=_ts(5, 12), water_cut=30.0)
    result = water_cut_jump(make_test(water_cut=35.0), ctx(previous_valid_test=prev))
    assert result.passed


def test_water_cut_jump_invalid_big_no_event():
    prev = make_test(ts_start=_ts(5), ts_end=_ts(5, 12), water_cut=30.0)
    result = water_cut_jump(make_test(water_cut=60.0), ctx(previous_valid_test=prev))
    assert not result.passed


def test_water_cut_jump_boundary_exact_threshold():
    prev = make_test(ts_start=_ts(5), ts_end=_ts(5, 12), water_cut=30.0)
    result = water_cut_jump(make_test(water_cut=45.0), ctx(previous_valid_test=prev))  # +15 п.п.
    assert result.passed


# --- gor_anomaly -------------------------------------------------------------------


def test_gor_anomaly_valid():
    result = gor_anomaly(make_test(gor=45.0), ctx(gor_history=[40.0, 42.0, 44.0]))
    assert result.passed


def test_gor_anomaly_invalid():
    result = gor_anomaly(make_test(gor=120.0), ctx(gor_history=[40.0, 42.0, 44.0]))
    assert not result.passed


def test_gor_anomaly_boundary_exact_threshold():
    result = gor_anomaly(make_test(gor=60.0), ctx(gor_history=[40.0, 40.0]))  # +50%
    assert result.passed


def test_gor_anomaly_insufficient_history_passes():
    result = gor_anomaly(make_test(gor=1000.0), ctx(gor_history=[40.0]))
    assert result.passed
    assert result.details["history_len"] == 1


# --- material_balance --------------------------------------------------------------


def test_material_balance_valid():
    sibling = make_test(well_id=2, q_liquid=48.0, q_oil=33.0)
    result = material_balance(
        make_test(q_liquid=50.0, q_oil=35.0),
        ctx(sibling_tests=[sibling], node_fact={"q_liquid_t": 100.0, "q_oil_t": 70.0}),
    )
    assert result.passed


def test_material_balance_invalid_large_discrepancy():
    sibling = make_test(well_id=2, q_liquid=10.0, q_oil=7.0)
    result = material_balance(
        make_test(q_liquid=50.0, q_oil=35.0),
        ctx(sibling_tests=[sibling], node_fact={"q_liquid_t": 100.0, "q_oil_t": 70.0}),
    )
    assert not result.passed
    assert "liquid" in result.message


def test_material_balance_boundary_exact_tolerance():
    # факт 100, сумма скважин 105 -> 5% ровно на границе допуска
    sibling = make_test(well_id=2, q_liquid=55.0, q_oil=38.5)
    result = material_balance(
        make_test(q_liquid=50.0, q_oil=35.0),
        ctx(sibling_tests=[sibling], node_fact={"q_liquid_t": 100.0, "q_oil_t": 70.0}),
    )
    assert result.passed


def test_material_balance_no_node_fact_passes():
    result = material_balance(make_test(), ctx(node_fact=None))
    assert result.passed


# --- staleness -----------------------------------------------------------------------


def test_staleness_valid_recent():
    prev = make_test(ts_start=_ts(6), ts_end=_ts(6, 12))
    result = staleness(make_test(ts_start=_ts(10)), ctx(previous_valid_test=prev))
    assert result.passed


def test_staleness_invalid_too_old():
    prev = make_test(ts_start=_ts(1), ts_end=_ts(1, 12))
    result = staleness(make_test(ts_start=_ts(25)), ctx(previous_valid_test=prev))
    assert not result.passed


def test_staleness_boundary_exact_threshold():
    prev_end = _ts(1, 0)
    test_start = prev_end + dt.timedelta(days=14)
    result = staleness(make_test(ts_start=test_start), ctx(previous_valid_test=make_test(ts_end=prev_end)))
    assert result.passed


def test_staleness_no_previous_passes():
    result = staleness(make_test(), ctx(previous_valid_test=None))
    assert result.passed


# --- telemetry_consistency ------------------------------------------------------------


def test_telemetry_consistency_valid():
    result = telemetry_consistency(make_test(q_liquid=50.0), ctx(telemetry_current=[20.0, 22.0, 19.0]))
    assert result.passed


def test_telemetry_consistency_invalid_no_current_despite_flow():
    result = telemetry_consistency(make_test(q_liquid=50.0), ctx(telemetry_current=[0.0, 0.2, 0.0]))
    assert not result.passed
    assert result.severity == "error"


def test_telemetry_consistency_boundary_exact_threshold():
    result = telemetry_consistency(make_test(q_liquid=50.0), ctx(telemetry_current=[5.0, 5.0, 5.0]))
    assert result.passed


def test_telemetry_consistency_no_data_passes():
    result = telemetry_consistency(make_test(q_liquid=50.0), ctx(telemetry_current=None))
    assert result.passed
    assert result.details["telemetry_available"] is False


def test_telemetry_consistency_low_flow_skips_check():
    result = telemetry_consistency(make_test(q_liquid=0.1), ctx(telemetry_current=[0.0]))
    assert result.passed


# --- evaluate() — сборка is_valid/validation_flags ------------------------------------


def test_evaluate_marks_invalid_on_error_rule():
    run = evaluate(make_test(duration_h=0.5), ctx())
    assert run.is_valid is False
    assert "duration_check" in run.validation_flags["errors"]


def test_evaluate_stays_valid_with_only_warnings():
    prev = make_test(ts_start=_ts(5), ts_end=_ts(5, 12), water_cut=30.0)
    run = evaluate(make_test(water_cut=60.0), ctx(previous_valid_test=prev))
    assert run.is_valid is True
    assert "water_cut_jump" in run.validation_flags["warnings"]
