"""4 обязательных сценария (как в test_loader.py и test_monthly_production.py):
нормальный файл, неизвестная скважина, повторная загрузка (идемпотентность),
строки, требующие внимания (не молчаливый пропуск)."""

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select

from src.domain.ingestion_log import IngestionQuarantine, IngestionRun
from src.domain.master_data import Completion, Field, Reservoir, Well, WellAlias
from src.domain.timeseries import DailyProduction
from src.ingestion.daily_report_loader import load
from src.ingestion.daily_report_source import DailyReportSource

FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = (
    Path(__file__).resolve().parents[2]
    / "src" / "ingestion" / "mappings" / "daily_report" / "standard_ru.yaml"
)


@pytest.fixture()
def two_known_wells(db_session):
    field = Field(name="Тестовое", field_type="oil")
    db_session.add(field)
    db_session.flush()

    reservoir = Reservoir(
        field_id=field.id, name="I", horizon_code="Ю-II",
        oil_density_t_m3=0.86, water_density_t_m3=1.0, density_confirmed=True,
    )
    db_session.add(reservoir)
    db_session.flush()

    wells = []
    for external_id, uwi in [("0001", "SYN-0001"), ("0002", "SYN-0002")]:
        well = Well(uwi=uwi, field_id=field.id, well_type="producer", status="active")
        db_session.add(well)
        db_session.flush()
        db_session.add(WellAlias(well_id=well.id, external_system="daily_report_ru", external_id=external_id))
        db_session.add(Completion(well_id=well.id, reservoir_id=reservoir.id, top_md=1000, bottom_md=1010, perf_date=dt.date(2020, 1, 1), status="open"))
        wells.append(well)
    db_session.flush()
    return wells


def test_normal_file_computes_rate_and_accumulated(db_session, two_known_wells):
    source = DailyReportSource(FIXTURES / "daily_prod_report_normal.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "success"
    assert result.records_loaded == 2
    assert result.records_quarantined == 0

    rows = {r.well_id: r for r in db_session.execute(select(DailyProduction)).scalars().all()}
    well1, well2 = two_known_wells

    # rate: Qн = 100*0.8*0.86=68.8 т/сут, часы=24 -> добыча=68.8 (без масштабирования)
    assert rows[well1.id].q_oil_t == pytest.approx(68.8)
    assert rows[well1.id].allocation_method == "extrapolated"

    # accumulated: Qн = 50*0.9*0.86=38.7, часы=12, но accumulated -> без домножения на 12/24
    assert rows[well2.id].q_oil_t == pytest.approx(38.7)
    assert rows[well2.id].allocation_method == "measured"


def test_unknown_well_goes_to_quarantine(db_session, two_known_wells):
    source = DailyReportSource(FIXTURES / "daily_prod_report_unknown_well.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "partial"
    assert result.records_loaded == 1
    assert result.records_quarantined == 1

    q = db_session.execute(select(IngestionQuarantine).where(IngestionQuarantine.run_id == result.run_id)).scalar_one()
    assert q.reason == "unknown_well"


def test_repeated_load_upserts_not_duplicates(db_session, two_known_wells):
    source = DailyReportSource(FIXTURES / "daily_prod_report_normal.csv", MAPPING)

    first = load(db_session, source)
    second = load(db_session, source)

    assert first.records_loaded == second.records_loaded == 2

    rows = db_session.execute(select(DailyProduction)).scalars().all()
    assert len(rows) == 2

    runs = db_session.execute(select(IngestionRun)).scalars().all()
    assert len(runs) == 2


def test_rows_needing_attention_are_quarantined_and_reported(db_session, two_known_wells):
    source = DailyReportSource(FIXTURES / "daily_prod_report_needs_attention.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "partial"
    assert result.records_loaded == 0
    assert result.records_quarantined == 3

    reasons = {
        q.reason
        for q in db_session.execute(select(IngestionQuarantine).where(IngestionQuarantine.run_id == result.run_id)).scalars()
    }
    assert reasons == {"invalid_value"}

    assert len(result.attention) == 3
    assert any("source_type" in "; ".join(r.need_confirmation_reasons) for r in result.attention)
    assert any("примечание" in r.validation_status for r in result.attention)
    assert any("часы работы = 0" in r.validation_status for r in result.attention)


def test_field_summary_and_unconfirmed_density_flag(db_session, two_known_wells):
    source = DailyReportSource(FIXTURES / "daily_prod_report_normal.csv", MAPPING)
    result = load(db_session, source)

    assert len(result.field_summaries) == 1
    summary = result.field_summaries[0]
    assert summary.wells_total == 2
    assert summary.wells_active == 2
    assert summary.wells_need_confirmation == 0  # плотность подтверждена в фикстуре

    for r in result.detailed_log:
        assert r.confidence == "high"


def test_missing_reservoir_flags_unconfirmed_density(db_session):
    field = Field(name="БезОбъекта", field_type="oil")
    db_session.add(field)
    db_session.flush()
    well = Well(uwi="NO-RES-0001", field_id=field.id, well_type="producer", status="active")
    db_session.add(well)
    db_session.flush()
    db_session.add(WellAlias(well_id=well.id, external_system="daily_report_ru", external_id="0001"))
    db_session.flush()

    csv_path = FIXTURES / "daily_prod_report_no_reservoir.csv"
    csv_path.write_text(
        "№ скважины,Дата,Способ эксплуатации,\"Часы работы, ч\",\"Дебит жидкости, м3/сут\","
        "\"Обводнённость, %\",\"Дебит газа, тыс.м3/сут\",Тип источника замера,Примечание\n"
        "0001,2024-06-01,ЭЦН,24,100,20,10,rate,\n",
        encoding="utf-8",
    )
    try:
        source = DailyReportSource(csv_path, MAPPING)
        result = load(db_session, source)
        assert result.records_loaded == 1  # плотность по умолчанию не блокирует расчёт
        assert result.detailed_log[0].need_confirmation is True
        assert result.detailed_log[0].confidence == "low"
    finally:
        csv_path.unlink()


def test_missing_file_fails_without_raising(db_session):
    source = DailyReportSource(FIXTURES / "does_not_exist.csv", MAPPING)

    result = load(db_session, source)

    assert result.status == "failed"
    assert "не найден" in result.error_message
