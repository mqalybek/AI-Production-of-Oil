"""Служебные таблицы слоя загрузки (src/ingestion): журнал запусков и карантин
записей, которые не удалось разобрать/сопоставить. Не промысловые данные —
эксплуатационный лог, поэтому отдельно от master_data/reference/timeseries.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class IngestionRun(Base):
    """Один запуск загрузки: источник, период, что получилось."""

    __tablename__ = "ingestion_run"
    __table_args__ = (
        CheckConstraint("source IN ('csv', 'synthetic', 'opcua')", name="ck_ingestion_run_source"),
        CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name="ck_ingestion_run_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column()
    period_label: Mapped[str | None] = mapped_column()
    source_path: Mapped[str | None] = mapped_column()
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(default="running")
    records_read: Mapped[int] = mapped_column(default=0)
    records_loaded: Mapped[int] = mapped_column(default=0)
    records_quarantined: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class IngestionQuarantine(Base):
    """Запись, которую не удалось разобрать/сопоставить — не молчаливый пропуск."""

    __tablename__ = "ingestion_quarantine"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('unknown_well', 'parse_error', 'unit_conversion_error', "
            "'schema_mismatch', 'invalid_value')",
            name="ck_ingestion_quarantine_reason",
        ),
        Index("ix_ingestion_quarantine_run_id", "run_id"),
        Index("ix_ingestion_quarantine_reason", "reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_run.id"))
    source: Mapped[str] = mapped_column()
    raw_data: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column()
    reason_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
