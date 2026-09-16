import datetime as dt

from src.domain.timeseries import DailyProduction, WellTest


def test_list_wells_filters_by_field_and_status(client, auth_headers, sample_field, make_well):
    make_well(status="active")
    make_well(status="idle")

    resp = client.get("/api/wells", params={"field": sample_field.id, "status": "active"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "active"


def test_get_well_card_404_for_unknown_uwi(client, auth_headers):
    resp = client.get("/api/wells/NOPE", headers=auth_headers)
    assert resp.status_code == 404


def test_get_well_card_returns_passport(client, auth_headers, make_well):
    well = make_well()
    resp = client.get(f"/api/wells/{well.uwi}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["uwi"] == well.uwi
    assert body["equipment"] == []
    assert body["completions"] == []


def test_well_production_day_granularity(client, auth_headers, db_session, make_well):
    well = make_well()
    db_session.add(
        DailyProduction(
            well_id=well.id, date=dt.date(2024, 6, 1), q_oil_t=10.0, q_liquid_t=15.0,
            q_water_m3=5.0, hours_on=24.0, ke=1.0, source="test",
        )
    )
    db_session.flush()

    resp = client.get(
        f"/api/wells/{well.uwi}/production",
        params={"from": "2024-06-01", "to": "2024-06-01", "granularity": "day"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["q_oil_t"] == 10.0


def test_well_production_month_granularity_sums(client, auth_headers, db_session, make_well):
    well = make_well()
    for day, q_oil in [(1, 10.0), (2, 20.0)]:
        db_session.add(
            DailyProduction(
                well_id=well.id, date=dt.date(2024, 6, day), q_oil_t=q_oil, q_liquid_t=q_oil + 5,
                q_water_m3=1.0, hours_on=24.0, ke=1.0, source="test",
            )
        )
    db_session.flush()

    resp = client.get(
        f"/api/wells/{well.uwi}/production",
        params={"from": "2024-06-01", "to": "2024-06-30", "granularity": "month"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["q_oil_t"] == 30.0


def test_well_tests_endpoint_paginates(client, auth_headers, db_session, make_well):
    well = make_well()
    for i in range(3):
        ts = dt.datetime(2024, 6, 1 + i, 8, tzinfo=dt.timezone.utc)
        db_session.add(
            WellTest(
                well_id=well.id, ts_start=ts, ts_end=ts + dt.timedelta(hours=4), duration_h=4.0,
                q_liquid=40.0, q_oil=30.0, q_water=10.0, water_cut=25.0, gor=50.0,
                is_valid=True, method="agzu",
            )
        )
    db_session.flush()

    resp = client.get(f"/api/wells/{well.uwi}/tests", params={"limit": 2}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
