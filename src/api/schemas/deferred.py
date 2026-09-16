from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class DeferredAggregateItem(BaseModel):
    group: int | None
    period: dt.date
    category: str
    volume_oil_t: float


class DeferredParetoItem(BaseModel):
    category: str
    reason_id: int | None
    reason_name: str | None
    volume_oil_t: float
    share_pct: float
    cumulative_pct: float
