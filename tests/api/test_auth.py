def test_login_success(client, make_api_user):
    make_api_user(username="ivanov", password="secret123", role="geologist")
    resp = client.post("/api/auth/login", json={"username": "ivanov", "password": "secret123"})
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert resp.json()["access_token"]


def test_login_wrong_password(client, make_api_user):
    make_api_user(username="ivanov", password="secret123")
    resp = client.post("/api/auth/login", json={"username": "ivanov", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_protected_route_requires_token(client):
    resp = client.get("/api/fields")
    assert resp.status_code == 401


def test_protected_route_with_token(client, auth_headers):
    resp = client.get("/api/fields", headers=auth_headers)
    assert resp.status_code == 200
