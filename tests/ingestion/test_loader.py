"""4 обязательных сценария: нормальный файл, неизвестная скважина, повторная
загрузка (идемпотентность), битый файл."""

import datetime as dt
from pathlib import Path

from sqlalchemy import select

from src.domain.ingestion_log import IngestionQuarantine, IngestionRun
from src.domain.timeseries import Measurement
from src.ingestion.base import Period
from src.ingestion.csv_source import CsvSource
from src.ingestion.loader import load

FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = Path(__file__).resolve().parents[2] / "src" / "ingestion" / "mappings" / "example_daily_report.yaml"
PERIOD = Period.parse("2024-01")


def test_normal_file_loads_into_measurement(db_session, known_well):
    source = CsvSource(FIXTURES / "daily_report_normal.csv", MAPPING)

    result = load(db_session, source, PERIOD)

    assert result.status == "success"
    assert result.records_quarantined == 0
    # 2 строки * 5 тегов (нефть/жидкость/вода/наработка/Рбуф) = 10
    assert result.records_loaded == 10

    rows = db_session.execute(select(Measurement).where(Measurement.well_id == known_well.id)).scalars().all()
    assert len(rows) == 10
    oil_values = sorted(r.value for r in rows if r.tag_id == 8)  # q_oil_daily
    assert oil_values == [18.1, 18.4]


def test_unknown_well_goes_to_quarantine_not_silently_dropped(db_session, known_well):
    source = CsvSource(FIXTURES / "daily_report_unknown_well.csv", MAPPING)

    result = load(db_session, source, PERIOD)

    assert result.status == "partial"
    # неизвестная скважина "9999" встречается в 5 тегах (нефть/жидкость/вода/наработка) = 4 тега в этом файле
    assert result.records_quarantined == 4
    assert result.records_loaded == 4  # тегов у известной скважины 0001 в этом файле — тоже 4

    quarantined = db_session.execute(
        select(IngestionQuarantine).where(IngestionQuarantine.run_id == result.run_id)
    ).scalars().all()
    assert len(quarantined) == 4
    assert all(q.reason == "unknown_well" for q in quarantined)
    assert all(q.raw_data.get("Скважина") == "9999" for q in quarantined)


def test_repeated_load_does_not_duplicate_rows(db_session, known_well):
    source = CsvSource(FIXTURES / "daily_report_normal.csv", MAPPING)

    first = load(db_session, source, PERIOD)
    second = load(db_session, source, PERIOD)

    assert first.records_loaded == second.records_loaded == 10

    rows = db_session.execute(select(Measurement).where(Measurement.well_id == known_well.id)).scalars().all()
    assert len(rows) == 10  # не 20 — upsert, а не дубли

    runs = db_session.execute(select(IngestionRun)).scalars().all()
    assert len(runs) == 2  # оба запуска залогированы, даже если данные не изменились


def test_repeated_load_updates_changed_values(db_session, known_well):
    source = CsvSource(FIXTURES / "daily_report_normal.csv", MAPPING)
    load(db_session, source, PERIOD)

    # второй запуск с другим значением по тому же (well_id, ts, tag) — должен перезаписать, не добавить
    modified = FIXTURES / "daily_report_normal_modified.csv"
    modified.write_text(
        "Скважина,Дата,\"Дебит нефти, т/сут\"\n0001,2024-01-05,99.9\n", encoding="utf-8"
    )
    try:
        load(db_session, CsvSource(modified, MAPPING), PERIOD)
        row = db_session.execute(
            select(Measurement).where(
                Measurement.well_id == known_well.id,
                Measurement.tag_id == 8,
                Measurement.ts == dt.datetime(2024, 1, 5, tzinfo=dt.timezone.utc),
            )
        ).scalar_one()
        assert row.value == 99.9
    finally:
        modified.unlink()


def test_corrupted_file_fails_without_raising(db_session):
    source = CsvSource(FIXTURES / "daily_report_corrupted.csv", MAPPING)

    result = load(db_session, source, PERIOD)

    assert result.status == "failed"
    assert result.error_message is not None
    assert result.records_loaded == 0

    run = db_session.get(IngestionRun, result.run_id)
    assert run.status == "failed"
    assert run.error_message


def test_missing_file_fails_without_raising(db_session):
    source = CsvSource(FIXTURES / "does_not_exist.csv", MAPPING)

    result = load(db_session, source, PERIOD)

    assert result.status == "failed"
    assert "не найден" in result.error_message
