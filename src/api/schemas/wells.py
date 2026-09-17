from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    field_type: str


class WellListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uwi: str
    name: str | None
    field_id: int
    well_type: str
    status: str


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipment_type: str
    type_size: str | None
    run_depth: float | None
    install_date: dt.date
    pull_date: dt.date | None


class CompletionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reservoir_id: int
    top_md: float
    bottom_md: float
    perf_date: dt.date
    status: str


class WellCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uwi: str
    gos_number: str | None
    name: str | None
    field_id: int
    well_type: str
    status: str
    spud_date: dt.date | None
    equipment: list[EquipmentOut]
    completions: list[CompletionOut]


class DailyProductionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: dt.date
    q_oil_t: float
    q_liquid_t: float
    q_water_m3: float
    q_gas_m3: float | None
    hours_on: float
    ke: float
    allocation_method: str | None
    confidence: str | None


class WellTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts_start: dt.datetime
    ts_end: dt.datetime
    duration_h: float
    q_liquid: float
    q_oil: float
    q_water: float
    q_gas: float | None
    water_cut: float | None
    gor: float | None
    method: str | None
    is_valid: bool
    validation_flags: dict | None


class TelemetryPoint(BaseModel):
    ts: dt.datetime
    tag: str
    value: float
    quality: str


class WellEvent(BaseModel):
    """Единая точка на шкале событий скважины: ГТМ, ремонт (оборудование) или простой."""

    kind: str  # 'gtm' | 'equipment' | 'downtime'
    date: dt.date
    title: str
    detail: str | None = None


class MonthlyProductionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_month: dt.date
    calendar_days: int
    working_days: int
    q_oil_t: float
    q_water_t: float
    q_gas_m3: float | None
    q_liquid_t: float
    gor: float | None
    water_cut_pct: float | None
    q_oil_rate_t_d: float | None


class WellMonthlySummaryOut(BaseModel):
    well_id: int
    uwi: str | None = None
    last_period: dt.date
    q_oil_t: float
    q_oil_rate_t_d: float | None
    water_cut_pct: float | None
    prev_q_oil_t: float | None
    delta_oil_t: float | None
    delta_oil_pct: float | None
    cumulative_oil_t: float
    months_count: int
