"""Чистая математика аллокации: КЭ, экстраполяция, аналог, K, инвариант суммы,
все краевые случаи из задания."""

import datetime as dt

import pytest

from src.calc.allocation import (
    ResolvedRates,
    TestPoint,
    WellDayInput,
    allocate_node_day,
    confidence_for_age,
    extrapolate_exponential,
    ke_from_hours_down,
    load_raw_config,
    resolve_config,
    resolve_ke,
    resolve_well_rates,
)

CFG = resolve_config(load_raw_config())


def _d(day: int) -> dt.date:
    return dt.date(2024, 1, day)


def _rates(well_id, oil, liquid, water, gas, method="measured", confidence="high") -> ResolvedRates:
    return ResolvedRates(
        well_id=well_id,
        rates={"oil": oil, "liquid": liquid, "water": water, "gas": gas},
        method=method,
        confidence=confidence,
        source_date=_d(10),
    )


# --- КЭ -----------------------------------------------------------------------


def test_ke_from_hours_down_no_downtime():
    assert ke_from_hours_down(0.0) == 1.0


def test_ke_from_hours_down_full_day():
    assert ke_from_hours_down(24.0) == 0.0


def test_ke_from_hours_down_partial():
    assert ke_from_hours_down(6.0) == pytest.approx(0.75)


def test_resolve_ke_prefers_telemetry():
    ke, source = resolve_ke(telemetry_hours_down=4.0, downtime_hours_down=10.0, rapport_hours_on=5.0)
    assert source == "telemetry"
    assert ke == pytest.approx((24 - 4) / 24)


def test_resolve_ke_falls_back_to_downtime_log():
    ke, source = resolve_ke(telemetry_hours_down=None, downtime_hours_down=8.0, rapport_hours_on=5.0)
    assert source == "downtime_log"
    assert ke == pytest.approx((24 - 8) / 24)


def test_resolve_ke_falls_back_to_daily_report():
    ke, source = resolve_ke(telemetry_hours_down=None, downtime_hours_down=None, rapport_hours_on=18.0)
    assert source == "daily_report"
    assert ke == pytest.approx(18 / 24)


def test_resolve_ke_no_data_defaults_to_full_day():
    ke, source = resolve_ke(None, None, None)
    assert source == "no_data"
    assert ke == 1.0


# --- confidence_for_age --------------------------------------------------------


def test_confidence_high_when_fresh():
    assert confidence_for_age(1, CFG) == "high"


def test_confidence_low_when_old():
    assert confidence_for_age(10, CFG) == "low"


def test_confidence_boundary_medium():
    assert confidence_for_age(CFG["confidence_bands"]["medium_max_age_days"], CFG) == "medium"


# --- extrapolate_exponential ---------------------------------------------------


def test_extrapolate_flat_when_single_point():
    assert extrapolate_exponential([(_d(1), 50.0)], _d(10)) == 50.0


def test_extrapolate_declining_trend():
    # 100 -> 81 за 10 суток -> темп ~2%/сут, ожидаем дальнейшее падение к 20 суткам
    value = extrapolate_exponential([(_d(1), 100.0), (_d(11), 81.0)], _d(21))
    assert value < 81.0
    assert value == pytest.approx(81.0 * (81.0 / 100.0), rel=0.01)


def test_extrapolate_no_positive_points_returns_zero():
    assert extrapolate_exponential([(_d(1), 0.0), (_d(5), 0.0)], _d(10)) == 0.0


# --- resolve_well_rates: measured / extrapolated / analog ----------------------


def test_resolve_well_rates_measured_when_fresh():
    tests = [TestPoint(date=_d(9), q_oil=30.0, q_liquid=40.0, q_water=10.0, q_gas=1200.0)]
    result = resolve_well_rates(1, tests, _d(10), [], CFG)
    assert result.method == "measured"
    assert result.confidence == "high"
    assert result.rates["oil"] == 30.0


def test_resolve_well_rates_extrapolated_when_stale():
    tests = [
        TestPoint(date=_d(1), q_oil=100.0, q_liquid=120.0, q_water=20.0, q_gas=4000.0),
        TestPoint(date=_d(5), q_oil=90.0, q_liquid=110.0, q_water=20.0, q_gas=3600.0),
    ]
    target = _d(25)  # заметно дальше max_test_age_days=14 от последнего замера
    result = resolve_well_rates(1, tests, target, [], CFG)
    assert result.method == "extrapolated"
    assert result.confidence == "low"
    assert result.rates["oil"] < 90.0  # тренд падающий


def test_resolve_well_rates_analog_when_no_tests_at_all():
    analogs = [
        TestPoint(date=_d(9), q_oil=20.0, q_liquid=25.0, q_water=5.0, q_gas=800.0),
        TestPoint(date=_d(8), q_oil=24.0, q_liquid=30.0, q_water=6.0, q_gas=900.0),
        TestPoint(date=_d(7), q_oil=22.0, q_liquid=27.0, q_water=5.0, q_gas=850.0),
    ]
    result = resolve_well_rates(1, [], _d(10), analogs, CFG)
    assert result.method == "analog"
    assert result.confidence == "low"
    assert result.rates["oil"] == 22.0  # медиана [20, 22, 24]


def test_resolve_well_rates_none_when_nothing_available():
    result = resolve_well_rates(1, [], _d(10), [], CFG)
    assert result is None


# --- allocate_node_day: инвариант суммы + краевые случаи -----------------------


def test_allocation_sum_matches_node_fact_exactly():
    wells = [
        WellDayInput(well_id=1, rates=_rates(1, 30.0, 40.0, 10.0, 1200.0), ke=1.0, ke_source="telemetry"),
        WellDayInput(well_id=2, rates=_rates(2, 17.0, 22.0, 5.0, 700.0), ke=0.9, ke_source="telemetry"),
        WellDayInput(well_id=3, rates=_rates(3, 11.0, 15.0, 4.0, 500.0), ke=0.8, ke_source="downtime_log"),
    ]
    node_fact = {"oil": 61.37, "liquid": 79.12, "water": 17.05, "gas": 2201.0}

    outputs = allocate_node_day(wells, node_fact, CFG["k_bounds"])

    for phase in ("oil", "liquid", "water", "gas"):
        total = round(sum(o.allocated[phase] for o in outputs), 2)
        assert total == round(node_fact[phase], 2), f"расходится по фазе {phase}"


def test_allocation_sum_matches_even_with_many_wells_and_odd_fact():
    # больше скважин + "неровный" факт узла — проверяем, что остаток округления
    # действительно гасится, а не накапливается
    wells = [
        WellDayInput(well_id=i, rates=_rates(i, 10.0 + i, 12.0 + i, 2.0, 300.0), ke=1.0, ke_source="telemetry")
        for i in range(1, 11)
    ]
    node_fact = {"oil": 133.333, "liquid": 199.997, "water": 20.001, "gas": 3000.0}

    outputs = allocate_node_day(wells, node_fact, CFG["k_bounds"])

    for phase in ("oil", "liquid", "water", "gas"):
        total = round(sum(o.allocated[phase] for o in outputs), 2)
        assert total == round(node_fact[phase], 2)


def test_allocation_k_out_of_bounds_still_applied_but_flagged():
    # факт в 2 раза больше суммы замеров -> K=2.0, вне [0.7, 1.3]
    wells = [WellDayInput(well_id=1, rates=_rates(1, 10.0, 12.0, 2.0, 400.0), ke=1.0, ke_source="telemetry")]
    node_fact = {"oil": 20.0, "liquid": 24.0, "water": 4.0, "gas": 800.0}

    outputs = allocate_node_day(wells, node_fact, CFG["k_bounds"])
    out = outputs[0]

    assert out.allocation_factor["oil"] == pytest.approx(2.0)
    assert "k_out_of_bounds:oil" in out.warnings
    assert out.allocated["oil"] == pytest.approx(20.0)  # K всё равно применён


def test_allocation_k_within_bounds_no_warning():
    wells = [WellDayInput(well_id=1, rates=_rates(1, 10.0, 12.0, 2.0, 400.0), ke=1.0, ke_source="telemetry")]
    node_fact = {"oil": 10.5, "liquid": 12.6, "water": 2.1, "gas": 420.0}

    outputs = allocate_node_day(wells, node_fact, CFG["k_bounds"])
    assert outputs[0].warnings == []


def test_allocation_well_down_all_day_gets_zero_but_still_included():
    wells = [
        WellDayInput(well_id=1, rates=_rates(1, 30.0, 40.0, 10.0, 1200.0), ke=1.0, ke_source="telemetry"),
        WellDayInput(well_id=2, rates=_rates(2, 20.0, 25.0, 5.0, 800.0), ke=0.0, ke_source="downtime_log"),
    ]
    node_fact = {"oil": 30.0, "liquid": 40.0, "water": 10.0, "gas": 1200.0}

    outputs = allocate_node_day(wells, node_fact, CFG["k_bounds"])
    by_well = {o.well_id: o for o in outputs}

    assert by_well[2].allocated["oil"] == 0.0
    assert by_well[2].ke == 0.0
    # инвариант всё равно держится
    assert round(sum(o.allocated["oil"] for o in outputs), 2) == 30.0


def test_allocation_no_measured_basis_flags_instead_of_crashing():
    # все КЭ = 0 (все скважины стоят), но факт на узле почему-то не нулевой —
    # патология данных, делить нечего, не должно падать
    wells = [WellDayInput(well_id=1, rates=_rates(1, 10.0, 12.0, 2.0, 400.0), ke=0.0, ke_source="telemetry")]
    node_fact = {"oil": 5.0, "liquid": 6.0, "water": 1.0, "gas": 200.0}

    outputs = allocate_node_day(wells, node_fact, CFG["k_bounds"])
    out = outputs[0]

    assert out.allocated["oil"] == 0.0
    assert out.allocation_factor["oil"] is None
    assert "no_measured_basis:oil" in out.warnings


def test_allocation_missing_node_fact_leaves_phase_unallocated():
    wells = [WellDayInput(well_id=1, rates=_rates(1, 10.0, 12.0, 2.0, None), ke=1.0, ke_source="telemetry")]
    node_fact = {"oil": 10.5, "liquid": 12.6, "water": 2.1, "gas": None}

    outputs = allocate_node_day(wells, node_fact, CFG["k_bounds"])
    out = outputs[0]

    assert out.allocation_factor["gas"] is None
    assert out.allocated["gas"] == 0.0
    assert out.allocation_factor["oil"] is not None
