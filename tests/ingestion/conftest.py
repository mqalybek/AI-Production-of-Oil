"""Минимальный набор мастер-данных и справочника тегов для тестов ingestion."""

import pytest

from src.domain.catalogs import MEASUREMENT_TAGS
from src.domain.master_data import Field, Well, WellAlias
from src.domain.reference import MeasurementTag


@pytest.fixture()
def measurement_tags(db_session):
    for i, (code, name, unit, min_v, max_v) in enumerate(MEASUREMENT_TAGS, start=1):
        db_session.add(
            MeasurementTag(id=i, code=code, name=name, unit=unit, min_value=min_v, max_value=max_v)
        )
    db_session.flush()


@pytest.fixture()
def known_well(db_session, measurement_tags):
    field = Field(name="Тестовое", field_type="oil")
    db_session.add(field)
    db_session.flush()

    well = Well(uwi="SYN-0001", field_id=field.id, well_type="producer", status="active")
    db_session.add(well)
    db_session.flush()

    db_session.add(WellAlias(well_id=well.id, external_system="1c", external_id="0001"))
    db_session.add(WellAlias(well_id=well.id, external_system="scada", external_id="SC-0001"))
    db_session.flush()

    return well
