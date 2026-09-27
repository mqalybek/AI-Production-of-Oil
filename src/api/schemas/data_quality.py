from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class DataQualityMetrics(BaseModel):
    period_start: dt.date
    period_end: dt.date
    quarantined_records: int
    invalid_tests: int
    valid_tests: int
    wells_without_recent_test: int
    low_confidence_allocation_days: int
    monthly_report_month: dt.date  # за какой (последний закрытый) месяц проверяли наличие отчётов
    wells_without_recent_monthly_report: int
    monthly_report_anomalies: int
