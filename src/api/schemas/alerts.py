from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    well_id: int | None
    node_id: int | None
    type: str
    severity: str
    ts_detected: dt.datetime
    ts_resolved: dt.datetime | None
    value: float | None
    threshold: float | None
    message: str
    is_acknowledged: bool
    acknowledged_by: str | None
    acknowledged_at: dt.datetime | None
    comment: str | None
    snoozed_until: dt.datetime | None


class AcknowledgeRequest(BaseModel):
    comment: str | None = None
