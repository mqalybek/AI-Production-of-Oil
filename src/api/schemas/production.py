from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class DailyFieldSummary(BaseModel):
    field_id: int
    field_name: str
    date: dt.date
    q_oil_t: float
    q_liquid_t: float
    q_water_m3: float
    wells_active: int
    wells_stopped: int


class ProductionSummaryPoint(BaseModel):
    period: dt.date
    q_oil_t: float
    plan_oil_t: float | None
