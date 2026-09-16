"""Раннер потерь добычи на синтетическом промысле: отчёт, разбивка по
простоям/причинам, агрегация, Парето, неотработанный фонд."""

import datetime as dt

import pytest
from sqlalchemy import select

from src.calc.deferred_runner import aggregate_losses, pareto_by_reason, run_period
from src.domain.master_data import Well
from src.domain.timeseries import DeferredProduction
from src.ingestion.base import Period


def _full_period(cfg) -> Period:
    return Period(cfg.history.start_date, cfg.history.start_date + dt.timedelta(days=cfg.history.days - 1))


def test_run_period_produces_report(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    report = run_period(db_session, _full_period(cfg))

    assert report.well_days_processed > 0
    assert report.total_loss_oil_t >= 0
    assert set(report.by_category).issubset({"downtime", "rate_reduction", "watering", "idle_fund"})


def test_run_period_writes_downtime_rows_with_reasons(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    run_period(db_session, _full_period(cfg))

    downtime_rows = db_session.execute(
        select(DeferredProduction).where(DeferredProduction.category == "downtime")
    ).scalars().all()

    assert downtime_rows  # в синтетике заложены отказы ЭЦН — простои есть
    assert all(r.reason_id is not None for r in downtime_rows)
    assert all(r.volume_oil_t >= 0 for r in downtime_rows)


def test_run_period_non_downtime_rows_have_no_reason(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    run_period(db_session, _full_period(cfg))

    rows = db_session.execute(
        select(DeferredProduction).where(DeferredProduction.category != "downtime")
    ).scalars().all()
    assert rows
    assert all(r.reason_id is None for r in rows)


def test_aggregate_losses_by_field_month(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    run_period(db_session, _full_period(cfg))

    rows = aggregate_losses(db_session, _full_period(cfg), group_by="field", time_bucket="month")
    assert rows
    assert all(r["group"] == tables["field"][0]["id"] for r in rows)
    # хотя бы одна помесячная точка
    months = {r["period"] for r in rows}
    assert len(months) >= 1


def test_aggregate_losses_by_well_day_matches_sum_of_categories(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    run_period(db_session, _full_period(cfg))

    well_id = tables["well"][0]["id"]
    rows = aggregate_losses(db_session, _full_period(cfg), group_by="well", time_bucket="day", well_ids=[well_id])

    direct_total = db_session.execute(
        select(DeferredProduction.volume_oil_t).where(DeferredProduction.well_id == well_id)
    ).scalars().all()

    # каждое r["volume_oil_t"] уже округлено до копеек по отдельности, поэтому
    # сумма агрегатов и точная сумма могут разойтись на пару копеек накоплением
    assert sum(r["volume_oil_t"] for r in rows) == pytest.approx(sum(direct_total), abs=0.05)


def test_pareto_by_reason_cumulative_reaches_100_percent(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    run_period(db_session, _full_period(cfg))

    pareto = pareto_by_reason(db_session, _full_period(cfg))
    assert pareto
    # неубывающая накопленная доля, последняя точка — 100%
    cumulative = [p["cumulative_pct"] for p in pareto]
    assert cumulative == sorted(cumulative)
    assert cumulative[-1] == 100.0


def test_idle_fund_for_mothballed_well(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    well_id = tables["well"][0]["id"]

    well = db_session.get(Well, well_id)
    well.status = "mothballed"
    db_session.flush()

    target_date = cfg.history.start_date + dt.timedelta(days=cfg.history.days - 5)
    report = run_period(db_session, Period(target_date, target_date), well_ids=[well_id])

    row = db_session.execute(
        select(DeferredProduction).where(
            DeferredProduction.well_id == well_id, DeferredProduction.date == target_date
        )
    ).scalar_one_or_none()

    assert row is not None
    assert row.category == "idle_fund"
    assert row.potential_basis in ("last_valid_test", "decline_trend")
    assert report.by_category.get("idle_fund", 0) > 0
