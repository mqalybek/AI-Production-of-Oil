import datetime as dt

from src.calc.monthly_loss import MonthlyLossInput, compute_month_loss


def test_compute_month_loss_multiplies_rate_by_idle_days():
    row = MonthlyLossInput(
        well_id=1, period_month=dt.date(2024, 6, 1), calendar_days=30, working_days=25, q_oil_rate_t_d=8.0
    )
    line = compute_month_loss(row)

    assert line.idle_days == 5
    assert line.volume_oil_t == 40.0


def test_compute_month_loss_none_when_no_idle_days():
    row = MonthlyLossInput(
        well_id=1, period_month=dt.date(2024, 6, 1), calendar_days=30, working_days=30, q_oil_rate_t_d=8.0
    )
    assert compute_month_loss(row) is None


def test_compute_month_loss_none_when_rate_unknown():
    row = MonthlyLossInput(
        well_id=1, period_month=dt.date(2024, 6, 1), calendar_days=30, working_days=0, q_oil_rate_t_d=None
    )
    assert compute_month_loss(row) is None


def test_full_month_idle_uses_fallback_rate():
    row = MonthlyLossInput(
        well_id=1, period_month=dt.date(2024, 6, 1), calendar_days=30, working_days=0,
        q_oil_rate_t_d=None, fallback_rate_t_d=8.0,
    )
    line = compute_month_loss(row)

    assert line.idle_days == 30
    assert line.volume_oil_t == 240.0


def test_own_rate_wins_over_fallback():
    row = MonthlyLossInput(
        well_id=1, period_month=dt.date(2024, 6, 1), calendar_days=30, working_days=25,
        q_oil_rate_t_d=8.0, fallback_rate_t_d=100.0,
    )
    assert compute_month_loss(row).volume_oil_t == 40.0
