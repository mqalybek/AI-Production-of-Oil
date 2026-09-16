"""Фикстуры с минимальным набором мастер-данных, нужным большинству тестов."""

import pytest

from src.domain.master_data import Field, Well


@pytest.fixture()
def sample_field(db_session):
    field = Field(name="Кумколь", field_type="oil")
    db_session.add(field)
    db_session.flush()
    return field


@pytest.fixture()
def sample_well(db_session, sample_field):
    well = Well(
        uwi="KZ-001-0042",
        name="Скв. 42",
        field_id=sample_field.id,
        well_type="producer",
        status="active",
    )
    db_session.add(well)
    db_session.flush()
    return well
