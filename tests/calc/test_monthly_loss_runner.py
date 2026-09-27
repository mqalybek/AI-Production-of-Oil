import datetime as dt

import pytest

from src.calc.monthly_loss_runner import aggregate_monthly_losses
from src.domain.master_data import Field, Well
from src.domain.monthly_production import MonthlyProduction
from src.ingestion.base import Period


def _make_well(db_session, field, uwi):
    well = Well(uwi=uwi, field_id=field.id, well_type="producer", status="active")
    db_session.add(well)
    db_session.flush()
    return well


def _add_month(db_session, well, month, calendar_days=30, working_days=30, q_oil_rate_t_d=8.0):
    db_session.add(
        MonthlyProduction(
            well_id=well.id,
            period_month=dt.date(2024, month, 1),
            calendar_days=calendar_days,
            working_days=working_days,
            q_oil_t=q_oil_rate_t_d * working_days,
            q_water_t=0.0,
            q_liquid_t=q_oil_rate_t_d * working_days,
            q_oil_rate_t_d=q_oil_rate_t_d,
            source="test",
        )
    )
    db_session.flush()


def _period() -> Period:
    return Period(dt.date(2024, 1, 1), dt.date(2024, 12, 31))


def test_aggregate_monthly_losses_by_well(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well = _make_well(db_session, field, "W-1")
    _add_month(db_session, well, 6, calendar_days=30, working_days=25, q_oil_rate_t_d=8.0)

    rows = aggregate_monthly_losses(db_session, _period(), group_by="well")

    assert len(rows) == 1
    assert rows[0]["group"] == well.id
    assert rows[0]["period"] == dt.date(2024, 6, 1)
    assert rows[0]["category"] == "downtime"
    assert rows[0]["volume_oil_t"] == 40.0


def test_aggregate_monthly_losses_skips_full_working_months(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well = _make_well(db_session, field, "W-1")
    _add_month(db_session, well, 6, calendar_days=30, working_days=30, q_oil_rate_t_d=8.0)

    rows = aggregate_monthly_losses(db_session, _period(), group_by="well")

    assert rows == []


def test_aggregate_monthly_losses_by_field_sums_wells(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well_a = _make_well(db_session, field, "W-1")
    well_b = _make_well(db_session, field, "W-2")
    _add_month(db_session, well_a, 6, calendar_days=30, working_days=25, q_oil_rate_t_d=8.0)  # 40т
    _add_month(db_session, well_b, 6, calendar_days=30, working_days=28, q_oil_rate_t_d=5.0)  # 10т

    rows = aggregate_monthly_losses(db_session, _period(), group_by="field")

    assert len(rows) == 1
    assert rows[0]["group"] == field.id
    assert rows[0]["volume_oil_t"] == 50.0


def test_aggregate_monthly_losses_rejects_unknown_group_by(db_session):
    with pytest.raises(ValueError):
        aggregate_monthly_losses(db_session, _period(), group_by="bogus")


def test_aggregate_monthly_losses_filters_by_well_ids(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well_a = _make_well(db_session, field, "W-1")
    well_b = _make_well(db_session, field, "W-2")
    _add_month(db_session, well_a, 6, calendar_days=30, working_days=25, q_oil_rate_t_d=8.0)
    _add_month(db_session, well_b, 6, calendar_days=30, working_days=25, q_oil_rate_t_d=8.0)

    rows = aggregate_monthly_losses(db_session, _period(), group_by="well", well_ids=[well_a.id])

    assert len(rows) == 1
    assert rows[0]["group"] == well_a.id


def _add_idle_month(db_session, well, year, month, calendar_days=31):
    db_session.add(
        MonthlyProduction(
            well_id=well.id, period_month=dt.date(year, month, 1), calendar_days=calendar_days,
            working_days=0, q_oil_t=0.0, q_water_t=0.0, q_liquid_t=0.0, q_oil_rate_t_d=None, source="test",
        )
    )
    db_session.flush()


def test_full_month_idle_uses_rate_of_last_working_month_before_period(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well = _make_well(db_session, field, "W-1")
    _add_month(db_session, well, 7, calendar_days=31, working_days=31, q_oil_rate_t_d=10.0)  # до периода
    _add_idle_month(db_session, well, 2024, 8)

    rows = aggregate_monthly_losses(
        db_session, Period(dt.date(2024, 8, 1), dt.date(2024, 8, 31)), group_by="well"
    )

    assert len(rows) == 1
    assert rows[0]["period"] == dt.date(2024, 8, 1)
    assert rows[0]["volume_oil_t"] == 310.0  # 10 т/сут x 31 сут простоя


def test_full_month_idle_ignores_too_old_rate(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well = _make_well(db_session, field, "W-1")
    _add_month(db_session, well, 1, calendar_days=31, working_days=31, q_oil_rate_t_d=10.0)
    _add_idle_month(db_session, well, 2024, 12)  # последний рабочий месяц — 11 месяцев назад

    rows = aggregate_monthly_losses(
        db_session, Period(dt.date(2024, 12, 1), dt.date(2024, 12, 31)), group_by="well"
    )

    assert rows == []
