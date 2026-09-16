"""Раннер должен ловить намеренно "грязные" замеры из генератора синтетики
(шаг 2) — это и есть материал, на котором валидация проверяется по-настоящему."""

import datetime as dt

from sqlalchemy import select

from src.calc.validation_runner import run_period
from src.domain.timeseries import WellTest
from src.ingestion.base import Period


def _full_period(cfg) -> Period:
    return Period(cfg.history.start_date, cfg.history.start_date + dt.timedelta(days=cfg.history.days))


def test_run_period_produces_report_over_synthetic_data(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    period = _full_period(cfg)

    report = run_period(db_session, period, persist=True)

    assert report.total_tests == len(tables["well_test"])
    assert report.total_tests > 0
    assert report.invalid_tests > 0, "в синтетике намеренно заложена грязь — что-то должно не пройти"


def test_run_period_catches_short_duration_tests(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    period = _full_period(cfg)

    report = run_period(db_session, period, persist=True)

    assert report.by_rule["duration_check"].failed > 0

    short_rows = db_session.execute(select(WellTest).where(WellTest.duration_h < 2.0)).scalars().all()
    assert short_rows
    for row in short_rows:
        assert row.is_valid is False
        assert "duration_check" in row.validation_flags["errors"]


def test_run_period_catches_impossible_physical_values(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    period = _full_period(cfg)

    run_period(db_session, period, persist=True)

    impossible_rows = db_session.execute(
        select(WellTest).where((WellTest.water_cut > 100) | (WellTest.q_oil < 0) | (WellTest.q_liquid < 0))
    ).scalars().all()
    assert impossible_rows
    for row in impossible_rows:
        assert row.is_valid is False
        assert "physical_bounds" in row.validation_flags["errors"]


def test_run_period_without_persist_does_not_touch_rows(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    period = _full_period(cfg)

    # запомним исходные флаги (все True — синтетика их сама не портит для "чистых" тестов
    # с точки зрения нашего рантайм-объекта, is_valid проставляет dirty.py)
    before = {
        row.id: row.is_valid for row in db_session.execute(select(WellTest)).scalars().all()
    }

    run_period(db_session, period, persist=False)

    after = {row.id: row.is_valid for row in db_session.execute(select(WellTest)).scalars().all()}
    assert before == after
