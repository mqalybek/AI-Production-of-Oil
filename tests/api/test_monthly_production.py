import datetime as dt

from src.domain.monthly_production import MonthlyProduction


def test_list_monthly_summaries_skips_wells_without_data(client, auth_headers, db_session, make_well):
    well_with_data = make_well()
    make_well()  # без данных — не должна попасть в сводку

    db_session.add(
        MonthlyProduction(
            well_id=well_with_data.id, period_month=dt.date(2024, 1, 1), calendar_days=31, working_days=30,
            q_oil_t=100.0, q_water_t=20.0, q_liquid_t=120.0, source="test",
        )
    )
    db_session.flush()

    resp = client.get("/api/monthly-production/wells", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["uwi"] == well_with_data.uwi


def test_list_monthly_summaries_filters_by_field(client, auth_headers, db_session, sample_field, make_well):
    well = make_well()
    db_session.add(
        MonthlyProduction(
            well_id=well.id, period_month=dt.date(2024, 1, 1), calendar_days=31, working_days=30,
            q_oil_t=100.0, q_water_t=20.0, q_liquid_t=120.0, source="test",
        )
    )
    db_session.flush()

    resp = client.get("/api/monthly-production/wells", params={"field": sample_field.id + 999}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
