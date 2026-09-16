"""Тесты мастер-данных: happy path + ограничения целостности БД."""

import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from src.domain.master_data import (
    Completion,
    Equipment,
    Field,
    GatheringNode,
    Reservoir,
    Well,
    WellAlias,
)


def test_create_field_reservoir_well(db_session):
    field = Field(name="Тенгиз", field_type="oil")
    db_session.add(field)
    db_session.flush()

    reservoir = Reservoir(field_id=field.id, name="Объект КТ-1", horizon_code="KT-1")
    db_session.add(reservoir)
    db_session.flush()

    well = Well(
        uwi="KZ-777-0001",
        gos_number="777-01",
        name="Скв. 1",
        field_id=field.id,
        well_type="producer",
        status="active",
        spud_date=dt.date(2020, 5, 1),
        wellhead_x=51.123,
        wellhead_y=45.678,
        altitude=112.0,
    )
    db_session.add(well)
    db_session.flush()

    assert well.id is not None
    assert well.uwi == "KZ-777-0001"


def test_well_uwi_must_be_unique(db_session, sample_field):
    db_session.add(
        Well(uwi="DUP-001", field_id=sample_field.id, well_type="producer", status="active")
    )
    db_session.flush()

    db_session.add(
        Well(uwi="DUP-001", field_id=sample_field.id, well_type="injector", status="active")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("bad_well_type", ["producer_extra", "", "PRODUCER"])
def test_well_type_check_constraint(db_session, sample_field, bad_well_type):
    db_session.add(
        Well(
            uwi="BAD-TYPE-001",
            field_id=sample_field.id,
            well_type=bad_well_type,
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_well_alias_maps_uwi_to_external_systems(db_session, sample_well):
    db_session.add(
        WellAlias(well_id=sample_well.id, external_system="scada", external_id="W-042-SC")
    )
    db_session.add(
        WellAlias(well_id=sample_well.id, external_system="1c", external_id="00000123")
    )
    db_session.flush()

    aliases = (
        db_session.query(WellAlias).filter(WellAlias.well_id == sample_well.id).all()
    )
    assert {a.external_system for a in aliases} == {"scada", "1c"}


def test_well_alias_external_id_unique_per_system(db_session, sample_well):
    db_session.add(
        WellAlias(well_id=sample_well.id, external_system="scada", external_id="W-042-SC")
    )
    db_session.flush()

    # другая скважина не может занять тот же внешний id в той же системе
    db_session.add(
        WellAlias(well_id=sample_well.id, external_system="scada", external_id="W-042-SC")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_completion_bottom_must_be_below_top(db_session, sample_well):
    reservoir = Reservoir(field_id=sample_well.field_id, name="Объект A")
    db_session.add(reservoir)
    db_session.flush()

    # корректный интервал перфорации: 2450.0 - 2465.5 м
    db_session.add(
        Completion(
            well_id=sample_well.id,
            reservoir_id=reservoir.id,
            top_md=2450.0,
            bottom_md=2465.5,
            perf_date=dt.date(2021, 3, 10),
            status="open",
        )
    )
    db_session.flush()

    # некорректно: подошва выше кровли
    db_session.add(
        Completion(
            well_id=sample_well.id,
            reservoir_id=reservoir.id,
            top_md=2465.5,
            bottom_md=2450.0,
            perf_date=dt.date(2021, 3, 10),
            status="open",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_equipment_pull_date_after_install_date(db_session, sample_well):
    db_session.add(
        Equipment(
            well_id=sample_well.id,
            equipment_type="esp",
            type_size="ЭЦН5-80",
            run_depth=1850.0,
            install_date=dt.date(2022, 1, 15),
            pull_date=dt.date(2023, 6, 1),
        )
    )
    db_session.flush()

    db_session.add(
        Equipment(
            well_id=sample_well.id,
            equipment_type="esp",
            install_date=dt.date(2022, 1, 15),
            pull_date=dt.date(2022, 1, 15),  # демонтаж в тот же день, что и монтаж
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_gathering_node_name_unique_within_field(db_session, sample_field):
    db_session.add(GatheringNode(field_id=sample_field.id, name="ГУ-3", node_type="gu"))
    db_session.flush()

    db_session.add(GatheringNode(field_id=sample_field.id, name="ГУ-3", node_type="agzu"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
