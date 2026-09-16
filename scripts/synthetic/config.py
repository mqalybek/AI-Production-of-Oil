"""Загрузка scripts/synthetic_config.yaml в типизированные pydantic-модели."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml
from pydantic import BaseModel


class Range(BaseModel):
    min: float
    max: float


class HistoryConfig(BaseModel):
    start_date: dt.date
    days: int


class FieldConfig(BaseModel):
    name: str
    reservoirs: list[str]


class WellsConfig(BaseModel):
    n_producers: int
    n_injectors: int
    n_piezometric: int


class GatheringConfig(BaseModel):
    n_agzu: int
    n_dns: int


class WaterCutConfig(BaseModel):
    start: Range
    end_high: Range
    fraction_high_wc_wells: float


class GorConfig(BaseModel):
    base_range_m3_t: Range
    days_to_bubble_point: Range
    ramp_up_factor: float


class ProductionConfig(BaseModel):
    qo_initial_t_d: Range
    arps_b: Range
    initial_annual_decline: Range
    well_test_interval_days: Range
    water_cut: WaterCutConfig
    gor: GorConfig


class PressuresConfig(BaseModel):
    p_buf_atm: Range
    p_buf_noise_std: float
    p_zatr_base_atm: Range
    p_zatr_depth_coef: float
    p_zatr_noise_std: float


class EspTelemetryConfig(BaseModel):
    measurement_interval_minutes: int
    current_a: Range
    load_pct: Range
    freq_hz: Range
    intake_pressure_atm: Range
    daily_cycle_amplitude_pct: float
    noise_std_pct: float
    esp_run_depth_m: Range


class PowerOutageConfig(BaseModel):
    events_per_year: float
    duration_hours: Range


class GtmConfig(BaseModel):
    events_per_year: Range
    oil_uplift_fraction: Range
    decline_acceleration_factor: Range


class EventsConfig(BaseModel):
    esp_mtbf_days: Range
    workover_duration_days: Range
    workover_events_per_well_per_year: float
    power_outage: PowerOutageConfig
    gtm: GtmConfig


class DirtyDataConfig(BaseModel):
    well_test_short_duration_fraction: Range
    well_test_outlier_fraction: Range
    telemetry_gap_probability_per_well_per_month: float
    telemetry_gap_duration_hours: Range
    impossible_value_count: int
    node_vs_wells_mismatch_pct: Range
    wells_with_long_gaps_count: int
    long_gap_duration_days: Range


class OutputConfig(BaseModel):
    csv_dir: str
    write_to_db: bool
    truncate_before_write: bool


class SyntheticConfig(BaseModel):
    seed: int
    history: HistoryConfig
    field: FieldConfig
    wells: WellsConfig
    gathering: GatheringConfig
    production: ProductionConfig
    pressures: PressuresConfig
    esp_telemetry: EspTelemetryConfig
    events: EventsConfig
    dirty_data: DirtyDataConfig
    output: OutputConfig


def load_config(path: str | Path) -> SyntheticConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return SyntheticConfig.model_validate(raw)
