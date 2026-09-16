"""Раннер аллокации на синтетических данных. Главный тест — инвариант:
сумма аллоцированной добычи по скважинам узла равна факту на узле,
по каждой фазе, по каждым суткам. Плюс краевые случаи: нет факта на узле,
новая скважина без замеров (analog)."""

import datetime as dt

from sqlalchemy import select

from src.calc.allocation_runner import run_period
from src.domain.master_data import Completion, Well, WellGatheringNodeHistory
from src.domain.timeseries import DailyProduction, NodeProduction
from src.ingestion.base import Period


def _full_period(cfg) -> Period:
    return Period(cfg.history.start_date, cfg.history.start_date + dt.timedelta(days=cfg.history.days - 1))


def test_run_period_produces_report(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    report = run_period(db_session, _full_period(cfg))

    assert report.total_well_days > 0
    assert report.allocated_well_days > 0


def test_allocation_sum_matches_node_fact_for_every_node_and_day(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    run_period(db_session, _full_period(cfg))

    node_facts = db_session.execute(select(NodeProduction)).scalars().all()
    assert node_facts  # синтетика без node_production бессмысленна для этого теста

    checked = 0
    for nf in node_facts:
        well_ids = [
            r["well_id"]
            for r in tables["well_gathering_node_history"]
            if r["node_id"] == nf.node_id and r["valid_from"] <= nf.date and (r["valid_to"] is None or r["valid_to"] > nf.date)
        ]
        if not well_ids:
            continue

        rows = db_session.execute(
            select(DailyProduction).where(
                DailyProduction.well_id.in_(well_ids),
                DailyProduction.date == nf.date,
                DailyProduction.source == "allocation",
            )
        ).scalars().all()
        if not rows:
            continue  # этот узел/дата не аллоцировались (например, no_node_data — тут не должно быть)

        checked += 1
        assert round(sum(r.q_oil_t for r in rows), 2) == round(nf.q_oil_t, 2), f"нефть разошлась: node={nf.node_id} date={nf.date}"
        assert round(sum(r.q_liquid_t for r in rows), 2) == round(nf.q_liquid_t, 2), f"жидкость разошлась: node={nf.node_id} date={nf.date}"
        assert round(sum(r.q_water_m3 for r in rows), 2) == round(nf.q_water_m3, 2), f"вода разошлась: node={nf.node_id} date={nf.date}"
        if nf.q_gas_m3 is not None:
            assert round(sum(r.q_gas_m3 or 0.0 for r in rows), 2) == round(nf.q_gas_m3, 2), f"газ разошёлся: node={nf.node_id} date={nf.date}"

    assert checked > 0, "инвариант суммы не был проверен ни разу — тест ничего не гарантирует"


def test_allocation_writes_method_and_confidence(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    run_period(db_session, _full_period(cfg))

    rows = db_session.execute(
        select(DailyProduction).where(DailyProduction.source == "allocation")
    ).scalars().all()
    assert rows
    for r in rows:
        assert r.allocation_method in ("measured", "extrapolated", "analog")
        assert r.confidence in ("high", "medium", "low")
        assert r.allocation_factor is not None
        assert set(r.allocation_factor.keys()) == {"oil", "liquid", "water", "gas"}


def test_allocation_no_node_data_day_is_skipped(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset
    node_id = tables["gathering_node"][0]["id"]
    target_date = cfg.history.start_date + dt.timedelta(days=10)

    row = db_session.execute(
        select(NodeProduction).where(NodeProduction.node_id == node_id, NodeProduction.date == target_date)
    ).scalar_one()
    db_session.delete(row)
    db_session.flush()

    report = run_period(db_session, Period(target_date, target_date), node_ids=[node_id])

    assert report.no_node_data_days == 1
    assert report.allocated_well_days == 0

    # существующая (синтетическая) строка на этот день не должна быть тронута аллокацией
    well_ids = [
        r["well_id"] for r in tables["well_gathering_node_history"] if r["node_id"] == node_id
    ]
    existing = db_session.execute(
        select(DailyProduction).where(DailyProduction.well_id.in_(well_ids), DailyProduction.date == target_date)
    ).scalars().all()
    assert all(r.source == "synthetic" for r in existing)


def test_allocation_new_well_without_tests_uses_analog(db_session, synthetic_dataset):
    cfg, tables = synthetic_dataset

    # берём существующую скважину с валидными замерами как донора reservoir_id/node_id
    donor_well = tables["well"][0]
    donor_completion = next(c for c in tables["completion"] if c["well_id"] == donor_well["id"])
    donor_node_history = next(h for h in tables["well_gathering_node_history"] if h["well_id"] == donor_well["id"])

    new_well = Well(
        uwi="NEW-WELL-001",
        field_id=donor_well["field_id"],
        well_type="producer",
        status="active",
    )
    db_session.add(new_well)
    db_session.flush()

    db_session.add(
        Completion(
            well_id=new_well.id,
            reservoir_id=donor_completion["reservoir_id"],
            top_md=2500.0,
            bottom_md=2510.0,
            perf_date=cfg.history.start_date,
            status="open",
        )
    )
    db_session.add(
        WellGatheringNodeHistory(
            well_id=new_well.id,
            node_id=donor_node_history["node_id"],
            valid_from=cfg.history.start_date,
            valid_to=None,
        )
    )
    db_session.flush()

    target_date = cfg.history.start_date + dt.timedelta(days=20)
    report = run_period(db_session, Period(target_date, target_date), node_ids=[donor_node_history["node_id"]])

    row = db_session.execute(
        select(DailyProduction).where(DailyProduction.well_id == new_well.id, DailyProduction.date == target_date)
    ).scalar_one_or_none()

    assert row is not None
    assert row.allocation_method == "analog"
    assert row.confidence == "low"
    assert report.method_counts.get("analog", 0) >= 1
