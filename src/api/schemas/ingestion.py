from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class WellDayResultOut(BaseModel):
    well_id: int
    uwi: str | None = None
    date: dt.date
    validation_status: str
    errors: list[str]
    need_confirmation: bool
    need_confirmation_reasons: list[str]
    hours_on: float
    ke: float | None
    q_oil_t: float | None = None
    q_liquid_t: float | None = None
    q_water_m3: float | None = None
    q_gas_m3: float | None = None
    q_liquid_m3: float | None = None
    gor_m3_t: float | None = None
    allocation_method: str | None = None
    confidence: str = "low"


class FieldDaySummaryOut(BaseModel):
    date: dt.date
    wells_total: int
    wells_active: int
    wells_idle: int
    wells_need_confirmation: int
    q_oil_t: float
    q_liquid_t: float
    q_water_m3: float
    q_gas_m3: float
    weighted_water_cut_pct: float | None


class DailyReportUploadResult(BaseModel):
    run_id: int
    status: str
    records_read: int
    records_loaded: int
    records_quarantined: int
    error_message: str | None
    field_summaries: list[FieldDaySummaryOut]
    attention: list[WellDayResultOut]
