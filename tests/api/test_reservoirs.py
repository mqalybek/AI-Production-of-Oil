from src.domain.master_data import Reservoir


def test_list_reservoirs_returns_density(client, auth_headers, db_session, sample_field):
    db_session.add(Reservoir(field_id=sample_field.id, name="I", horizon_code="Ю-II", oil_density_t_m3=0.86))
    db_session.add(Reservoir(field_id=sample_field.id, name="II", horizon_code="Ю-III-1"))
    db_session.flush()

    resp = client.get("/api/reservoirs", params={"field": sample_field.id}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    by_name = {r["name"]: r for r in body}
    assert by_name["I"]["oil_density_t_m3"] == 0.86
    assert by_name["II"]["oil_density_t_m3"] is None


def test_update_reservoir_density(client, auth_headers, db_session, sample_field):
    reservoir = Reservoir(field_id=sample_field.id, name="I", horizon_code="Ю-II")
    db_session.add(reservoir)
    db_session.flush()

    resp = client.patch(
        f"/api/reservoirs/{reservoir.id}", json={"oil_density_t_m3": 0.84}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["oil_density_t_m3"] == 0.84

    db_session.refresh(reservoir)
    assert reservoir.oil_density_t_m3 == 0.84


def test_update_unknown_reservoir_404(client, auth_headers):
    resp = client.patch("/api/reservoirs/999999", json={"oil_density_t_m3": 0.84}, headers=auth_headers)
    assert resp.status_code == 404
