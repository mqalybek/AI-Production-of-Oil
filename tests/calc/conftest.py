"""Загрузка таблиц синтетического генератора прямо в тестовую (rollback-able)
сессию — через тот же порядок таблиц, что и scripts/synthetic/writer.py, но
через session.execute(), а не отдельное соединение, чтобы участвовать в
транзакции теста."""

import pandas as pd
import pytest
from sqlalchemy import text

from scripts.generate_synthetic_field import build_tables
from scripts.synthetic import writer as synthetic_writer
from scripts.synthetic.config import SyntheticConfig
from src.domain import Base


def load_tables_into_session(session, tables: dict) -> None:
    for name in synthetic_writer.TABLE_ORDER:
        if name not in tables:
            continue
        df = tables[name] if isinstance(tables[name], pd.DataFrame) else pd.DataFrame(tables[name])
        if df.empty:
            continue
        sa_table = Base.metadata.tables[name]
        records = df.astype(object).where(df.notna(), None).to_dict("records")
        session.execute(sa_table.insert(), records)
    session.flush()

    # таблицы писались с явными id (как в scripts/synthetic/writer.py) —
    # без этого следующий INSERT через ORM (без явного id) столкнётся с уже
    # занятым id, т.к. sequence сама не сдвинулась
    for name in synthetic_writer.TABLES_WITH_EXPLICIT_IDS:
        if name not in tables:
            continue
        session.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {name}), 1))"
            )
        )


@pytest.fixture()
def synthetic_dataset(db_session):
    """Небольшой, но НЕ вычищенный синтетический промысел (доли "грязи" —
    дефолтные из scripts/synthetic_config.yaml), загруженный в БД."""
    import numpy as np

    cfg = SyntheticConfig.model_validate(
        {
            "seed": 42,
            "history": {"start_date": "2024-01-01", "days": 90},
            "field": {"name": "Тестовое", "reservoirs": ["Объект А"]},
            "wells": {"n_producers": 8, "n_injectors": 2, "n_piezometric": 0},
            "gathering": {"n_agzu": 2, "n_dns": 1},
            "production": {
                "qo_initial_t_d": {"min": 10, "max": 80},
                "arps_b": {"min": 0.3, "max": 0.8},
                "initial_annual_decline": {"min": 0.08, "max": 0.25},
                "well_test_interval_days": {"min": 4, "max": 6},
                "water_cut": {
                    "start": {"min": 0.0, "max": 0.15},
                    "end_high": {"min": 0.7, "max": 0.9},
                    "fraction_high_wc_wells": 0.5,
                },
                "gor": {
                    "base_range_m3_t": {"min": 40, "max": 100},
                    "days_to_bubble_point": {"min": 40, "max": 80},
                    "ramp_up_factor": 1.6,
                },
            },
            "pressures": {
                "p_buf_atm": {"min": 8, "max": 25},
                "p_buf_noise_std": 0.8,
                "p_zatr_base_atm": {"min": 10, "max": 30},
                "p_zatr_depth_coef": 0.01,
                "p_zatr_noise_std": 0.5,
            },
            "esp_telemetry": {
                "measurement_interval_minutes": 240,
                "esp_run_depth_m": {"min": 1500, "max": 2500},
                "current_a": {"min": 25, "max": 60},
                "load_pct": {"min": 40, "max": 95},
                "freq_hz": {"min": 40, "max": 50},
                "intake_pressure_atm": {"min": 5, "max": 20},
                "daily_cycle_amplitude_pct": 5,
                "noise_std_pct": 3,
            },
            "events": {
                "esp_mtbf_days": {"min": 60, "max": 120},
                "workover_duration_days": {"min": 3, "max": 8},
                "workover_events_per_well_per_year": 0.3,
                "power_outage": {"events_per_year": 6, "duration_hours": {"min": 1, "max": 6}},
                "gtm": {
                    "events_per_year": {"min": 2, "max": 5},
                    "oil_uplift_fraction": {"min": 0.15, "max": 0.6},
                    "decline_acceleration_factor": {"min": 1.3, "max": 2.0},
                },
            },
            "dirty_data": {
                "well_test_short_duration_fraction": {"min": 0.05, "max": 0.08},
                "well_test_outlier_fraction": {"min": 0.02, "max": 0.03},
                "telemetry_gap_probability_per_well_per_month": 0.3,
                "telemetry_gap_duration_hours": {"min": 3, "max": 18},
                "impossible_value_count": 5,
                "node_vs_wells_mismatch_pct": {"min": 3, "max": 12},
                "wells_with_long_gaps_count": 1,
                "long_gap_duration_days": {"min": 10, "max": 20},
            },
            "output": {"csv_dir": "unused", "write_to_db": False, "truncate_before_write": False},
        }
    )
    rng = np.random.default_rng(cfg.seed)
    tables = build_tables(cfg, rng)
    load_tables_into_session(db_session, tables)
    return cfg, tables
