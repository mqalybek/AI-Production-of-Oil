import datetime as dt

from src.calc.monthly_analysis_runner import get_well_summary, summarize_wells
from src.domain.master_data import Field, Well
from src.domain.monthly_production import MonthlyProduction


def _make_well(db_session, field, uwi):
    well = Well(uwi=uwi, field_id=field.id, well_type="producer", status="active")
    db_session.add(well)
    db_session.flush()
    return well


def _add_month(db_session, well, month, q_oil_t, q_liquid_t=None):
    db_session.add(
        MonthlyProduction(
            well_id=well.id,
            period_month=dt.date(2024, month, 1),
            calendar_days=30,
            working_days=30,
            q_oil_t=q_oil_t,
            q_water_t=(q_liquid_t or q_oil_t * 1.2) - q_oil_t,
            q_liquid_t=q_liquid_t or q_oil_t * 1.2,
            source="test",
        )
    )
    db_session.flush()


def test_get_well_summary_reads_points_in_order(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well = _make_well(db_session, field, "W-1")

    _add_month(db_session, well, 2, 120.0)
    _add_month(db_session, well, 1, 100.0)  # добавлен вторым — проверяем сортировку по period_month

    summary = get_well_summary(db_session, well.id)

    assert summary.last_period == dt.date(2024, 2, 1)
    assert summary.prev_q_oil_t == 100.0
    assert summary.delta_oil_t == 20.0


def test_get_well_summary_none_for_well_without_data(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well = _make_well(db_session, field, "W-1")

    assert get_well_summary(db_session, well.id) is None


def test_summarize_wells_skips_wells_without_data(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well_with_data = _make_well(db_session, field, "W-1")
    well_without_data = _make_well(db_session, field, "W-2")
    _add_month(db_session, well_with_data, 1, 100.0)

    summaries = summarize_wells(db_session, [well_with_data.id, well_without_data.id])

    assert len(summaries) == 1
    assert summaries[0].well_id == well_with_data.id


def test_since_filters_out_older_months(db_session):
    field = Field(name="Т", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well = _make_well(db_session, field, "W-1")
    _add_month(db_session, well, 1, 100.0)
    _add_month(db_session, well, 2, 120.0)

    summary = get_well_summary(db_session, well.id, since=dt.date(2024, 2, 1))

    assert summary.months_count == 1
    assert summary.last_period == dt.date(2024, 2, 1)
