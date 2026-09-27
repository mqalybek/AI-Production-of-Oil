import io

from src.domain.master_data import WellAlias


def _alias(db_session, well, external_id: str) -> None:
    db_session.add(WellAlias(well_id=well.id, external_system="daily_report_ru", external_id=external_id))
    db_session.flush()


def test_list_daily_report_mappings(client, auth_headers):
    resp = client.get("/api/ingestion/daily-report/mappings", headers=auth_headers)
    assert resp.status_code == 200
    assert "standard_ru" in resp.json()


def test_upload_daily_report_normal_file(client, auth_headers, db_session, make_well):
    well = make_well()
    _alias(db_session, well, "0001")

    csv_content = (
        "№ скважины,Дата,Способ эксплуатации,\"Часы работы, ч\",\"Дебит жидкости, м3/сут\","
        "\"Обводнённость, %\",\"Дебит газа, тыс.м3/сут\",Тип источника замера,Примечание\n"
        "0001,2024-06-01,ЭЦН,24,100,20,10,rate,\n"
    )
    files = {"file": ("report.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}

    resp = client.post("/api/ingestion/daily-report", files=files, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["records_loaded"] == 1
    assert body["records_quarantined"] == 0
    assert len(body["field_summaries"]) == 1
    assert body["field_summaries"][0]["q_oil_t"] == 68.8


def test_upload_with_unknown_mapping_returns_400(client, auth_headers):
    files = {"file": ("report.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    resp = client.post(
        "/api/ingestion/daily-report", files=files, params={"mapping": "nonexistent"}, headers=auth_headers
    )
    assert resp.status_code == 400


def test_upload_report_needing_attention_resolves_uwi(client, auth_headers, db_session, make_well):
    well = make_well()
    _alias(db_session, well, "0001")

    csv_content = (
        "№ скважины,Дата,Способ эксплуатации,\"Часы работы, ч\",\"Дебит жидкости, м3/сут\","
        "\"Обводнённость, %\",\"Дебит газа, тыс.м3/сут\",Тип источника замера,Примечание\n"
        "0001,2024-06-01,ЭЦН,24,100,20,10,,\n"  # без source_type
    )
    files = {"file": ("report.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}

    resp = client.post("/api/ingestion/daily-report", files=files, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["records_loaded"] == 0
    assert body["records_quarantined"] == 1
    assert len(body["attention"]) == 1
    assert body["attention"][0]["uwi"] == well.uwi
    assert body["attention"][0]["need_confirmation"] is True


def test_upload_requires_auth(client):
    files = {"file": ("report.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    resp = client.post("/api/ingestion/daily-report", files=files)
    assert resp.status_code == 401


def test_upload_rejects_mapping_path_traversal(client, auth_headers):
    files = {"file": ("report.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    resp = client.post(
        "/api/ingestion/daily-report", files=files,
        params={"mapping": "../monthly_production/standard_ru"}, headers=auth_headers,
    )
    assert resp.status_code == 400


def test_upload_invalidates_cached_aggregates(client, auth_headers, db_session, make_well):
    well = make_well()
    _alias(db_session, well, "0001")
    params = {"from": "2024-06-01", "to": "2024-06-01"}

    before = client.get("/api/data-quality", params=params, headers=auth_headers).json()
    assert before["low_confidence_allocation_days"] == 0  # теперь это значение в кэше

    csv_content = (
        "№ скважины,Дата,Способ эксплуатации,\"Часы работы, ч\",\"Дебит жидкости, м3/сут\","
        "\"Обводнённость, %\",\"Дебит газа, тыс.м3/сут\",Тип источника замера,Примечание\n"
        "0001,2024-06-01,ЭЦН,24,100,20,10,rate,\n"  # плотность не подтверждена -> confidence=low
    )
    files = {"file": ("report.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    assert client.post("/api/ingestion/daily-report", files=files, headers=auth_headers).status_code == 200

    after = client.get("/api/data-quality", params=params, headers=auth_headers).json()
    assert after["low_confidence_allocation_days"] == 1
