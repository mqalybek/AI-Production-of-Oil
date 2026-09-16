"""Минимальные фикстуры для тестов алертов — точечный контроль над
данными важнее статистического реализма синтетики (в отличие от тестов
src/calc, где нужен был инвариант на большом наборе)."""

import datetime as dt
import itertools

import pytest

from src.domain.catalogs import MEASUREMENT_TAGS
from src.domain.master_data import Field, GatheringNode, Well, WellGatheringNodeHistory
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
def sample_field(db_session, measurement_tags):
    field = Field(name="Тестовое", field_type="oil")
    db_session.add(field)
    db_session.flush()
    return field


@pytest.fixture()
def sample_node(db_session, sample_field):
    node = GatheringNode(field_id=sample_field.id, name="АГЗУ-1", node_type="agzu")
    db_session.add(node)
    db_session.flush()
    return node


@pytest.fixture()
def make_well(db_session, sample_field, sample_node):
    def _make(status: str = "active", node=None) -> Well:
        n = next(_well_counter)
        well = Well(uwi=f"W-{n:04d}", field_id=sample_field.id, well_type="producer", status=status)
        db_session.add(well)
        db_session.flush()
        target_node = sample_node if node is None else node
        if target_node is not None:
            db_session.add(
                WellGatheringNodeHistory(well_id=well.id, node_id=target_node.id, valid_from=dt.date(2023, 1, 1), valid_to=None)
            )
            db_session.flush()
        return well

    return _make
