import datetime as dt

from src.domain.api_access import ProductionPlan
from src.domain.timeseries import DailyProduction


def test_daily_summary_sums_field_wells(client, auth_headers, db_session, sample_field, make_well):
    well = make_well()
    db_session.add(
        DailyProduction(
            well_id=well.id, date=dt.date(2024, 6, 1), q_oil_t=12.0, q_liquid_t=20.0,
            q_water_m3=8.0, hours_on=24.0, ke=1.0, source="test",
        )
    )
    db_session.flush()

    resp = client.get(
        "/api/production/daily", params={"field": sample_field.id, "date": "2024-06-01"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["q_oil_t"] == 12.0
    assert body[0]["wells_active"] == 1


def test_production_summary_includes_plan(client, auth_headers, db_session, sample_field, make_well):
    well = make_well()
    db_session.add(
        DailyProduction(
            well_id=well.id, date=dt.date(2024, 6, 15), q_oil_t=100.0, q_liquid_t=150.0,
            q_water_m3=50.0, hours_on=24.0, ke=1.0, source="test",
        )
    )
    db_session.add(ProductionPlan(field_id=sample_field.id, period_month=dt.date(2024, 6, 1), planned_oil_t=3000.0))
    db_session.flush()

    resp = client.get(
        "/api/production/summary",
        params={"period": "2024-06", "field": sample_field.id, "granularity": "month"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["q_oil_t"] == 100.0
    assert body[0]["plan_oil_t"] == 3000.0
