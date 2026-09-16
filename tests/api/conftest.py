"""TestClient поверх той же тестовой БД/транзакции, что и db_session —
get_db переопределён, чтобы роуты видели откатываемые тестовые данные."""

import itertools

import pytest
from fastapi.testclient import TestClient

from src.api.cache import cache
from src.api.deps import get_db
from src.api.main import app
from src.api.security import hash_password
from src.domain.api_access import ApiUser
from src.domain.catalogs import MEASUREMENT_TAGS
from src.domain.master_data import Field, Well
from src.domain.reference import MeasurementTag

_well_counter = itertools.count(1)


@pytest.fixture()
def measurement_tags(db_session):
    for i, (code, name, unit, min_v, max_v) in enumerate(MEASUREMENT_TAGS, start=1):
        db_session.add(
            MeasurementTag(id=i, code=code, name=name, unit=unit, min_value=min_v, max_value=max_v)
        )
    db_session.flush()


@pytest.fixture()
def sample_field(db_session):
    field = Field(name="Тестовое", field_type="oil")
    db_session.add(field)
    db_session.flush()
    return field


@pytest.fixture()
def make_well(db_session, sample_field):
    def _make(status: str = "active") -> Well:
        n = next(_well_counter)
        well = Well(uwi=f"W-{n:04d}", field_id=sample_field.id, well_type="producer", status=status)
        db_session.add(well)
        db_session.flush()
        return well

    return _make


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    cache.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def make_api_user(db_session):
    def _make(username: str = "tester", password: str = "pass1234", role: str = "manager") -> ApiUser:
        user = ApiUser(username=username, password_hash=hash_password(password), role=role)
        db_session.add(user)
        db_session.flush()
        return user

    return _make


@pytest.fixture()
def auth_headers(client, make_api_user):
    make_api_user(username="tester", password="pass1234", role="manager")
    resp = client.post("/api/auth/login", json={"username": "tester", "password": "pass1234"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
