"""Чистая логика, числовые примеры проверяются в столбик."""

import datetime as dt

from src.calc.monthly_analysis import MonthlyPoint, summarize_well


def _point(month: int, q_oil_t: float, **kwargs) -> MonthlyPoint:
    defaults = dict(q_liquid_t=q_oil_t * 1.2, q_water_t=q_oil_t * 0.2, water_cut_pct=None, q_oil_rate_t_d=None)
    defaults.update(kwargs)
    return MonthlyPoint(period_month=dt.date(2024, month, 1), q_oil_t=q_oil_t, **defaults)


def test_no_points_returns_none():
    assert summarize_well(1, []) is None


def test_single_point_has_no_delta():
    summary = summarize_well(1, [_point(1, 100.0)])
    assert summary.q_oil_t == 100.0
    assert summary.prev_q_oil_t is None
    assert summary.delta_oil_t is None
    assert summary.delta_oil_pct is None
    assert summary.cumulative_oil_t == 100.0
    assert summary.months_count == 1


def test_delta_between_two_months():
    summary = summarize_well(1, [_point(1, 100.0), _point(2, 120.0)])
    assert summary.last_period == dt.date(2024, 2, 1)
    assert summary.prev_q_oil_t == 100.0
    assert summary.delta_oil_t == 20.0
    assert summary.delta_oil_pct == 20.0  # +20%
    assert summary.cumulative_oil_t == 220.0
    assert summary.months_count == 2


def test_declining_production_has_negative_delta():
    summary = summarize_well(1, [_point(1, 100.0), _point(2, 80.0)])
    assert summary.delta_oil_t == -20.0
    assert summary.delta_oil_pct == -20.0


def test_delta_pct_none_when_prev_is_zero():
    summary = summarize_well(1, [_point(1, 0.0), _point(2, 50.0)])
    assert summary.delta_oil_t == 50.0
    assert summary.delta_oil_pct is None  # деление на 0 избегаем, а не даём inf


def test_cumulative_sums_all_months():
    points = [_point(m, 100.0) for m in range(1, 4)]
    summary = summarize_well(1, points)
    assert summary.cumulative_oil_t == 300.0
    assert summary.months_count == 3
