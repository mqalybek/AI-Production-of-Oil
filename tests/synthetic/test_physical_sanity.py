"""Проверка, что генератор синтетического промысла выдаёт физически
правдоподобные данные — кроме умышленно "грязных" записей (они и обязаны
нарушать эти проверки, иначе валидацию не на чем тестировать).

Работает на маленьком конфиге (3 скважины, 45 суток) — не гоняет полный
3-летний промысел, но использует тот же код генерации (build_tables), так
что проверяет реальный пайплайн, а не его копию.
"""

import numpy as np
import pytest

from scripts.generate_synthetic_field import build_tables
from scripts.synthetic.config import SyntheticConfig

_TEST_CONFIG = {
    "seed": 7,
    "history": {"start_date": "2024-01-01", "days": 45},
    "field": {"name": "Тестовое", "reservoirs": ["Объект А", "Объект Б"]},
    "wells": {"n_producers": 5, "n_injectors": 2, "n_piezometric": 1},
    "gathering": {"n_agzu": 2, "n_dns": 1},
    "production": {
        "qo_initial_t_d": {"min": 5, "max": 120},
        "arps_b": {"min": 0.3, "max": 0.8},
        "initial_annual_decline": {"min": 0.08, "max": 0.25},
        "well_test_interval_days": {"min": 3, "max": 5},
        "water_cut": {
            "start": {"min": 0.0, "max": 0.15},
            "end_high": {"min": 0.85, "max": 0.95},
            "fraction_high_wc_wells": 0.5,
        },
        "gor": {
            "base_range_m3_t": {"min": 40, "max": 120},
            "days_to_bubble_point": {"min": 20, "max": 40},
            "ramp_up_factor": 1.8,
        },
    },
    "pressures": {
        "p_buf_atm": {"min": 8, "max": 25},
        "p_buf_noise_std": 0.8,
        "p_zatr_base_atm": {"min": 10, "max": 30},
        "p_zatr_depth_coef": 0.01,
        "p_zatr_noise_std": 0.6,
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
        "esp_mtbf_days": {"min": 20, "max": 40},
        "workover_duration_days": {"min": 3, "max": 10},
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
        "impossible_value_count": 3,
        "node_vs_wells_mismatch_pct": {"min": 3, "max": 12},
        "wells_with_long_gaps_count": 1,
        "long_gap_duration_days": {"min": 5, "max": 10},
    },
    "output": {"csv_dir": "unused", "write_to_db": False, "truncate_before_write": False},
}


@pytest.fixture(scope="module")
def tables():
    cfg = SyntheticConfig.model_validate(_TEST_CONFIG)
    rng = np.random.default_rng(cfg.seed)
    return build_tables(cfg, rng)


def test_daily_production_within_physical_ranges(tables):
    df = tables["daily_production"]
    assert len(df) > 0
    assert (df["q_oil_t"] >= 0).all()
    assert (df["q_liquid_t"] >= 0).all()
    assert (df["q_water_m3"] >= 0).all()
    assert df["hours_on"].between(0, 24).all()
    assert df["ke"].between(0, 1).all()
    # жидкость = нефть + вода (с точностью до округления)
    assert np.allclose(df["q_liquid_t"], df["q_oil_t"] + df["q_water_m3"], atol=0.05)


def test_well_test_valid_records_within_physical_bounds(tables):
    df = tables["well_test"]
    clean = df[df["is_valid"]]
    assert len(clean) > 0, "в валидных замерах должно быть хоть что-то"

    assert clean["water_cut"].between(0, 100).all()
    assert (clean["q_liquid"] >= 0).all()
    assert (clean["q_oil"] >= 0).all()
    assert (clean["q_water"] >= 0).all()
    assert (clean["duration_h"] >= 2).all()
    assert (clean["ts_end"] > clean["ts_start"]).all()


def test_well_test_contains_intentionally_dirty_records(tables):
    """Если тут пусто — значит dirty.py сломан и валидацию тестировать не на чем."""
    df = tables["well_test"]
    dirty = df[~df["is_valid"]]
    assert len(dirty) > 0

    has_short_duration = (dirty["duration_h"] < 2).any()
    has_impossible_water_cut = (dirty["water_cut"] > 100).any()
    has_negative_rate = ((dirty["q_oil"] < 0) | (dirty["q_liquid"] < 0) | (dirty["q_water"] < 0)).any()
    assert has_short_duration
    assert has_impossible_water_cut or has_negative_rate


def test_measurement_tags_and_values_are_sane(tables):
    df = tables["measurement"]
    assert len(df) > 0
    assert df["quality"].isin(["good", "suspect", "bad"]).all()
    assert df["value"].notna().all()
    known_tag_ids = [r["id"] for r in tables["measurement_tag"]]
    assert df["tag_id"].isin(known_tag_ids).all()


def test_node_production_close_to_sum_of_wells(tables):
    """Расхождение узел/сумма скважин заложено намеренно (3-12%), но не безгранично."""
    dp = tables["daily_production"].copy()
    node_map = {
        r["well_id"]: r["node_id"]
        for r in tables["well_gathering_node_history"]
        if r["valid_to"] is None
    }
    dp = dp[dp["well_id"].isin(node_map)]
    dp["node_id"] = dp["well_id"].map(node_map)
    expected = dp.groupby(["node_id", "date"])["q_oil_t"].sum()

    node_df = tables["node_production"].set_index(["node_id", "date"])["q_oil_t"]
    common_idx = expected.index.intersection(node_df.index)
    assert len(common_idx) > 0

    ratio = (node_df.loc[common_idx] / expected.loc[common_idx]).dropna()
    # расхождение сконфигурировано до 12%, оставляем запас на округления
    assert ratio.between(0.85, 1.15).all()
