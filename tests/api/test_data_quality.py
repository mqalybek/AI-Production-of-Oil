import datetime as dt

from src.domain.monthly_production import MonthlyProduction
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


def test_data_quality_counts_wells_without_monthly_report(client, auth_headers, db_session, make_well):
    reported_well = make_well()
    make_well()  # без отчёта за этот месяц
    db_session.add(
        MonthlyProduction(
            well_id=reported_well.id, period_month=dt.date(2024, 6, 1), calendar_days=30, working_days=30,
            q_oil_t=200.0, q_water_t=0.0, q_liquid_t=200.0, source="test",
        )
    )
    db_session.flush()

    resp = client.get(
        "/api/data-quality", params={"from": "2024-06-01", "to": "2024-06-30"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["wells_without_recent_monthly_report"] == 1


def test_data_quality_counts_monthly_report_anomalies(client, auth_headers, db_session, make_well):
    well = make_well()
    db_session.add(
        MonthlyProduction(
            well_id=well.id, period_month=dt.date(2024, 6, 1), calendar_days=30, working_days=31,
            q_oil_t=200.0, q_water_t=0.0, q_liquid_t=200.0, source="test",
        )
    )
    db_session.flush()

    resp = client.get(
        "/api/data-quality", params={"from": "2024-06-01", "to": "2024-06-30"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["monthly_report_anomalies"] == 1
