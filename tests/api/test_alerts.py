import datetime as dt

from src.domain.alerts import Alert


def test_list_alerts_filters_active(client, auth_headers, db_session, make_well):
    well = make_well()
    db_session.add(
        Alert(
            well_id=well.id, type="well_stopped", severity="critical",
            ts_detected=dt.datetime.now(dt.timezone.utc), message="тест", is_acknowledged=False,
        )
    )
    db_session.add(
        Alert(
            well_id=well.id, type="well_stopped", severity="critical",
            ts_detected=dt.datetime.now(dt.timezone.utc), ts_resolved=dt.datetime.now(dt.timezone.utc),
            message="тест2", is_acknowledged=False,
        )
    )
    db_session.flush()

    resp = client.get("/api/alerts", params={"status": "active"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["message"] == "тест"


def test_acknowledge_alert_sets_user_from_token(client, auth_headers, db_session, make_well):
    well = make_well()
    alert = Alert(
        well_id=well.id, type="well_stopped", severity="critical",
        ts_detected=dt.datetime.now(dt.timezone.utc), message="тест", is_acknowledged=False,
    )
    db_session.add(alert)
    db_session.flush()

    resp = client.post(
        f"/api/alerts/{alert.id}/acknowledge", json={"comment": "иду смотреть"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_acknowledged"] is True
    assert body["acknowledged_by"] == "tester"
    assert body["comment"] == "иду смотреть"


def test_acknowledge_unknown_alert_404(client, auth_headers):
    resp = client.post("/api/alerts/999999/acknowledge", json={}, headers=auth_headers)
    assert resp.status_code == 404
