"""Сценарии из спецификации: rate, accumulated, без source_type, часы=0,
часы=24, частичные часы без причины (валидация должна упасть)."""

import datetime as dt

from src.calc.daily_report import WellDayInput, compute_well_day, summarize_field_day

DATE = dt.date(2024, 6, 1)


def _inp(**kwargs) -> WellDayInput:
    defaults = dict(
        well_id=1, date=DATE, source_type="rate", hours_on=24.0, q_liquid_m3=100.0,
        water_cut_pct=20.0, q_gas_thousand_m3=10.0, comment=None,
        oil_density_t_m3=0.86, water_density_t_m3=1.0, density_confirmed=True,
    )
    defaults.update(kwargs)
    return WellDayInput(**defaults)


def test_rate_scales_by_hours_worked():
    result = compute_well_day(
        _inp(source_type="rate", hours_on=12.0, q_liquid_m3=100.0, water_cut_pct=0.0, comment="Ремонт 12ч")
    )
    # дебит нефти = 100 * 1.0 * 0.86 = 86 т/сут, добыча = 86 * 12/24 = 43
    assert result.q_oil_t == 43.0
    assert result.allocation_method == "extrapolated"
    assert result.validation_status == "OK"


def test_accumulated_does_not_scale_by_hours():
    result = compute_well_day(
        _inp(source_type="accumulated", hours_on=12.0, q_liquid_m3=100.0, water_cut_pct=0.0, comment="Ремонт 12ч")
    )
    # накопительный счётчик — берём как есть, без домножения на часы/24
    assert result.q_oil_t == 86.0
    assert result.allocation_method == "measured"


def test_missing_source_type_does_not_compute_production():
    result = compute_well_day(_inp(source_type=None))
    assert result.q_oil_t is None
    assert result.q_liquid_t is None
    assert result.need_confirmation is True
    assert any("source_type" in r for r in result.need_confirmation_reasons)


def test_unknown_source_type_treated_as_missing():
    result = compute_well_day(_inp(source_type="something_else"))
    assert result.q_oil_t is None
    assert result.need_confirmation is True


def test_hours_zero_with_zero_rate_is_valid():
    result = compute_well_day(_inp(hours_on=0.0, q_liquid_m3=0.0, comment="Простой: ТКРС"))
    assert result.validation_status == "OK"
    assert result.q_oil_t == 0.0
    assert result.ke == 0.0


def test_hours_zero_with_nonzero_rate_is_data_error():
    result = compute_well_day(_inp(hours_on=0.0, q_liquid_m3=50.0))
    assert result.validation_status != "OK"
    assert "часы работы = 0" in result.validation_status
    assert result.q_oil_t is None


def test_hours_full_24_is_valid_without_comment():
    result = compute_well_day(_inp(hours_on=24.0, comment=None))
    assert result.validation_status == "OK"
    assert result.ke == 1.0


def test_partial_hours_without_comment_fails_validation():
    result = compute_well_day(_inp(hours_on=20.0, comment=None))
    assert result.validation_status != "OK"
    assert "примечание" in result.validation_status
    assert result.q_oil_t is None


def test_partial_hours_with_comment_is_valid():
    result = compute_well_day(_inp(hours_on=20.0, comment="Остановка 4ч — осмотр устья"))
    assert result.validation_status == "OK"
    assert result.q_oil_t is not None


def test_hours_out_of_range_is_error():
    result = compute_well_day(_inp(hours_on=25.0))
    assert result.validation_status != "OK"
    assert result.ke is None


def test_negative_liquid_rate_is_error_not_absolute_value():
    result = compute_well_day(_inp(q_liquid_m3=-10.0))
    assert "отрицательный дебит жидкости" in result.validation_status
    assert result.q_oil_t is None


def test_water_cut_out_of_range_is_error():
    result = compute_well_day(_inp(water_cut_pct=150.0))
    assert "обводнённость" in result.validation_status


def test_unconfirmed_density_flags_need_confirmation_but_still_computes():
    result = compute_well_day(_inp(density_confirmed=False))
    assert result.q_oil_t is not None  # не блокирует расчёт, только предупреждает
    assert result.need_confirmation is True
    assert result.confidence == "low"


def test_confirmed_density_and_clean_data_is_high_confidence():
    result = compute_well_day(_inp(density_confirmed=True))
    assert result.need_confirmation is False
    assert result.confidence == "high"


def test_gas_oil_ratio_computed_when_oil_present():
    result = compute_well_day(_inp(q_gas_thousand_m3=20.0, water_cut_pct=0.0, hours_on=24.0, q_liquid_m3=100.0))
    # Qн = 100*0.86 = 86 т/сут, Qг = 20*1000 = 20000 м3/сут, ГФ = 20000/86
    assert result.gor_m3_t == round(20000 / 86, 2)


def test_gas_oil_ratio_none_when_no_oil_produced():
    result = compute_well_day(_inp(water_cut_pct=100.0, q_gas_thousand_m3=5.0))
    assert result.q_oil_t == 0.0
    assert result.gor_m3_t is None  # защита от деления на 0


def test_summarize_field_day_aggregates_and_weights_water_cut():
    well_a = compute_well_day(_inp(well_id=1, q_liquid_m3=100.0, water_cut_pct=0.0, hours_on=24.0))
    well_b = compute_well_day(_inp(well_id=2, q_liquid_m3=100.0, water_cut_pct=50.0, hours_on=24.0))
    well_c_no_source = compute_well_day(_inp(well_id=3, source_type=None))

    summary = summarize_field_day(DATE, [well_a, well_b, well_c_no_source])

    assert summary.wells_total == 3
    assert summary.wells_active == 3
    assert summary.wells_need_confirmation == 1
    # вода: 0 + 50 = 50 м3, жидкость: 100 + 100 = 200 м3 -> 25%
    assert summary.weighted_water_cut_pct == 25.0
