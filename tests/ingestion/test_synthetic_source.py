"""SyntheticSource должен проходить через тот же пайплайн matching/upsert,
что и настоящий источник — источники взаимозаменяемы, как и задумано."""

import datetime as dt

import numpy as np

from scripts.generate_synthetic_field import build_tables
from scripts.synthetic import writer
from scripts.synthetic.config import SyntheticConfig
from src.domain.master_data import Field, Well, WellAlias
from src.domain.reference import MeasurementTag
from src.ingestion.base import Period
from src.ingestion.loader import load
from src.ingestion.synthetic_source import SyntheticSource

_TINY_CONFIG = {
    "seed": 1,
    "history": {"start_date": "2024-01-01", "days": 5},
    "field": {"name": "Тестовое", "reservoirs": ["Объект А"]},
    "wells": {"n_producers": 2, "n_injectors": 1, "n_piezometric": 0},
    "gathering": {"n_agzu": 1, "n_dns": 1},
    "production": {
        "qo_initial_t_d": {"min": 20, "max": 40},
        "arps_b": {"min": 0.3, "max": 0.8},
        "initial_annual_decline": {"min": 0.08, "max": 0.25},
        "well_test_interval_days": {"min": 3, "max": 5},
        "water_cut": {
            "start": {"min": 0.0, "max": 0.1},
            "end_high": {"min": 0.5, "max": 0.6},
            "fraction_high_wc_wells": 0.5,
        },
        "gor": {
            "base_range_m3_t": {"min": 40, "max": 60},
            "days_to_bubble_point": {"min": 100, "max": 200},
            "ramp_up_factor": 1.5,
        },
    },
    "pressures": {
        "p_buf_atm": {"min": 8, "max": 25},
        "p_buf_noise_std": 0.5,
        "p_zatr_base_atm": {"min": 10, "max": 30},
        "p_zatr_depth_coef": 0.01,
        "p_zatr_noise_std": 0.3,
    },
    "esp_telemetry": {
        "measurement_interval_minutes": 1440,  # раз в сутки — чтобы данных было мало
        "esp_run_depth_m": {"min": 1500, "max": 2000},
        "current_a": {"min": 25, "max": 60},
        "load_pct": {"min": 40, "max": 95},
        "freq_hz": {"min": 40, "max": 50},
        "intake_pressure_atm": {"min": 5, "max": 20},
        "daily_cycle_amplitude_pct": 0,
        "noise_std_pct": 1,
    },
    "events": {
        "esp_mtbf_days": {"min": 300, "max": 400},
        "workover_duration_days": {"min": 3, "max": 5},
        "workover_events_per_well_per_year": 0.0,
        "power_outage": {"events_per_year": 0, "duration_hours": {"min": 1, "max": 2}},
        "gtm": {
            "events_per_year": {"min": 0, "max": 0},
            "oil_uplift_fraction": {"min": 0.1, "max": 0.2},
            "decline_acceleration_factor": {"min": 1.1, "max": 1.2},
        },
    },
    "dirty_data": {
        "well_test_short_duration_fraction": {"min": 0.0, "max": 0.0},
        "well_test_outlier_fraction": {"min": 0.0, "max": 0.0},
        "telemetry_gap_probability_per_well_per_month": 0.0,
        "telemetry_gap_duration_hours": {"min": 1, "max": 2},
        "impossible_value_count": 0,
        "node_vs_wells_mismatch_pct": {"min": 3, "max": 5},
        "wells_with_long_gaps_count": 0,
        "long_gap_duration_days": {"min": 1, "max": 2},
    },
    "output": {"csv_dir": "unused", "write_to_db": False, "truncate_before_write": False},
}


def test_synthetic_source_round_trip(tmp_path, db_session, measurement_tags):
    cfg = SyntheticConfig.model_validate(_TINY_CONFIG)
    rng = np.random.default_rng(cfg.seed)
    tables = build_tables(cfg, rng)
    writer.write_csv(tables, tmp_path)

    # мастер-данные, нужные для резолюции скважин matching'ом — как будто
    # они уже приехали в БД (в реальности этим занимается отдельный процесс,
    # ingestion работает поверх уже существующих скважин)
    for row in tables["field"]:
        db_session.add(Field(**row))
    db_session.flush()
    for row in tables["well"]:
        db_session.add(Well(**row))
    db_session.flush()
    for row in tables["well_alias"]:
        db_session.add(WellAlias(**row))
    db_session.flush()

    source = SyntheticSource(tmp_path, external_system="scada")
    period = Period(cfg.history.start_date, cfg.history.start_date + dt.timedelta(days=cfg.history.days))

    result = load(db_session, source, period)

    assert result.records_read > 0
    assert result.records_loaded > 0
    assert result.records_quarantined == 0, "все скважины из синтетики должны резолвиться через well_alias"
    assert result.status == "success"
