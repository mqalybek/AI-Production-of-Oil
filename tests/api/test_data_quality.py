import datetime as dt

from src.domain.timeseries import WellTest


def test_data_quality_counts_invalid_tests(client, auth_headers, db_session, make_well):
    well = make_well()
    ts = dt.datetime(2024, 6, 1, 8, tzinfo=dt.timezone.utc)
    db_session.add(
        WellTest(
            well_id=well.id, ts_start=ts, ts_end=ts + dt.timedelta(hours=4), duration_h=4.0,
            q_liquid=40.0, q_oil=30.0, q_water=10.0, water_cut=25.0, gor=50.0,
            is_valid=False, method="agzu",
        )
    )
    db_session.flush()

    resp = client.get(
        "/api/data-quality", params={"from": "2024-06-01", "to": "2024-06-01"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["invalid_tests"] == 1
    assert body["wells_without_recent_test"] == 0
