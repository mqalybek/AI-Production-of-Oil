import datetime as dt

from src.domain.reference import DowntimeReason
from src.domain.timeseries import DeferredProduction


def test_deferred_aggregate_by_well(client, auth_headers, db_session, make_well):
    well = make_well()
    db_session.add(
        DeferredProduction(
            well_id=well.id, date=dt.date(2024, 6, 1), category="rate_reduction",
            volume_oil_t=5.0, potential_basis="last_valid_test",
        )
    )
    db_session.flush()

    resp = client.get(
        "/api/deferred", params={"from": "2024-06-01", "to": "2024-06-01", "groupby": "well"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["group"] == well.id
    assert body[0]["volume_oil_t"] == 5.0


def test_deferred_filters_by_well(client, auth_headers, db_session, make_well):
    well_a = make_well()
    well_b = make_well()
    db_session.add_all(
        [
            DeferredProduction(
                well_id=well_a.id, date=dt.date(2024, 6, 1), category="rate_reduction",
                volume_oil_t=5.0, potential_basis="last_valid_test",
            ),
            DeferredProduction(
                well_id=well_b.id, date=dt.date(2024, 6, 1), category="rate_reduction",
                volume_oil_t=9.0, potential_basis="last_valid_test",
            ),
        ]
    )
    db_session.flush()

    resp = client.get(
        "/api/deferred",
        params={"from": "2024-06-01", "to": "2024-06-01", "groupby": "well", "well": well_a.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["group"] == well_a.id


def test_deferred_pareto_by_reason(client, auth_headers, db_session, make_well):
    reason = DowntimeReason(code="pump_failure", name="Отказ насоса")
    db_session.add(reason)
    db_session.flush()

    well = make_well()
    db_session.add(
        DeferredProduction(
            well_id=well.id, date=dt.date(2024, 6, 1), category="downtime", reason_id=reason.id,
            volume_oil_t=8.0, potential_basis="last_valid_test",
        )
    )
    db_session.flush()

    resp = client.get(
        "/api/deferred", params={"from": "2024-06-01", "to": "2024-06-01", "groupby": "reason"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["reason_name"] == "Отказ насоса"
    assert body[0]["cumulative_pct"] == 100.0
