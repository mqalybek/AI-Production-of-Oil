"""4 обязательных сценария (как в test_loader.py): нормальный файл,
неизвестная скважина, повторная загрузка (идемпотентность), битые строки.
Плюс — деривация недостающих полей и резолюция объекта/горизонта."""

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select

from src.domain.ingestion_log import IngestionQuarantine, IngestionRun
from src.domain.master_data import Field, Reservoir, Well, WellAlias
from src.domain.monthly_production import MonthlyProduction
from src.ingestion.monthly_production_loader import load
from src.ingestion.monthly_production_source import MonthlyProductionSource

FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = (
    Path(__file__).resolve().parents[2]
    / "src" / "ingestion" / "mappings" / "monthly_production" / "standard_ru.yaml"
)


@pytest.fixture()
def known_well(db_session):
    field = Field(name="Тестовое", field_type="oil")
    db_session.add(field)
    db_session.flush()

    db_session.add(Reservoir(field_id=field.id, name="I", horizon_code="Ю-II"))
    db_session.flush()

    well = Well(uwi="SYN-0001", field_id=field.id, well_type="producer", status="active")
    db_session.add(well)
    db_session.flush()

    db_session.add(WellAlias(well_id=well.id, external_system="monthly_report_ru", external_id="0001"))
    db_session.flush()

    return well


def test_normal_file_loads_and_resolves_reservoir(db_session, known_well):
    source = MonthlyProductionSource(FIXTURES / "monthly_production_normal.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "success"
    assert result.records_loaded == 2
    assert result.records_quarantined == 0

    rows = db_session.execute(
        select(MonthlyProduction).where(MonthlyProduction.well_id == known_well.id).order_by(MonthlyProduction.period_month)
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].period_month == dt.date(2024, 1, 1)
    assert rows[0].q_oil_t == 750
    assert rows[0].q_liquid_t == 885
    assert rows[0].water_cut_pct == 15.25
    assert rows[0].reservoir_id is not None


def test_unknown_well_goes_to_quarantine(db_session, known_well):
    source = MonthlyProductionSource(FIXTURES / "monthly_production_unknown_well.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "partial"
    assert result.records_loaded == 1
    assert result.records_quarantined == 1

    q = db_session.execute(select(IngestionQuarantine).where(IngestionQuarantine.run_id == result.run_id)).scalar_one()
    assert q.reason == "unknown_well"


def test_repeated_load_upserts_not_duplicates(db_session, known_well):
    source = MonthlyProductionSource(FIXTURES / "monthly_production_normal.csv", MAPPING)

    first = load(db_session, source)
    second = load(db_session, source)

    assert first.records_loaded == second.records_loaded == 2

    rows = db_session.execute(
        select(MonthlyProduction).where(MonthlyProduction.well_id == known_well.id)
    ).scalars().all()
    assert len(rows) == 2

    runs = db_session.execute(select(IngestionRun)).scalars().all()
    assert len(runs) == 2


def test_row_errors_are_quarantined_not_silently_dropped(db_session, known_well):
    source = MonthlyProductionSource(FIXTURES / "monthly_production_row_errors.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "partial"
    assert result.records_loaded == 1  # только первая строка валидна
    assert result.records_quarantined == 2  # "not_a_number" + пустые обязательные поля

    reasons = {
        q.reason
        for q in db_session.execute(select(IngestionQuarantine).where(IngestionQuarantine.run_id == result.run_id)).scalars()
    }
    assert reasons == {"parse_error"}


def test_derives_missing_water_and_water_cut_and_rate(db_session, known_well):
    csv_path = FIXTURES / "monthly_production_derived.csv"
    csv_path.write_text(
        "Скважина,Дата,Объект,Горизонт,Календарные дни,Отр дни,Доб нефти,Доб жидкости\n"
        "0001,2024-01-01,I,Ю-II,31,30,750,885\n",
        encoding="utf-8",
    )
    try:
        source = MonthlyProductionSource(csv_path, MAPPING)
        result = load(db_session, source)
        assert result.status == "success"

        row = db_session.execute(
            select(MonthlyProduction).where(MonthlyProduction.well_id == known_well.id)
        ).scalar_one()
        assert row.q_water_t == pytest.approx(135.0)  # 885 - 750
        assert row.water_cut_pct == pytest.approx(100 * 135 / 885)
        assert row.q_oil_rate_t_d == pytest.approx(750 / 30)
    finally:
        csv_path.unlink()


def test_missing_required_columns_fails_without_raising(db_session):
    source = MonthlyProductionSource(FIXTURES / "monthly_production_missing_required.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "failed"
    assert result.error_message is not None
    assert result.records_loaded == 0


def test_missing_file_fails_without_raising(db_session):
    source = MonthlyProductionSource(FIXTURES / "does_not_exist.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "failed"
    assert "не найден" in result.error_message
