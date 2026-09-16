"""Алерты: срабатывания детекторов (src/alerts/detectors.py) и подписки на
рассылку в Telegram (src/alerts/telegram_bot.py).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base

ALERT_TYPES = (
    "well_stopped",
    "water_cut_rise",
    "gor_rise",
    "pressure_anomaly",
    "stale_test",
    "mtbf_approach",
    "production_drop",
    "data_gap",
    "node_stopped_cascade",
)
SEVERITIES = ("info", "warning", "critical")
ROLES = ("geologist", "mechanic", "manager")


class Alert(Base):
    """Одно срабатывание детектора. well_id и node_id — скважина или узел
    (для группового каскадного алерта, node_stopped_cascade), хотя бы одно
    из двух обязательно заполнено.
    """

    __tablename__ = "alert"
    __table_args__ = (
        CheckConstraint("well_id IS NOT NULL OR node_id IS NOT NULL", name="ck_alert_scope"),
        CheckConstraint(f"type IN {ALERT_TYPES!r}", name="ck_alert_type"),
        CheckConstraint(f"severity IN {SEVERITIES!r}", name="ck_alert_severity"),
        Index("ix_alert_well_id_type_active", "well_id", "type", "ts_resolved"),
        Index("ix_alert_node_id_type_active", "node_id", "type", "ts_resolved"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    well_id: Mapped[int | None] = mapped_column(ForeignKey("well.id"))
    node_id: Mapped[int | None] = mapped_column(ForeignKey("gathering_node.id"))
    type: Mapped[str] = mapped_column()
    severity: Mapped[str] = mapped_column()
    ts_detected: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ts_resolved: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    value: Mapped[float | None] = mapped_column()
    threshold: Mapped[float | None] = mapped_column()
    message: Mapped[str] = mapped_column(Text)
    is_acknowledged: Mapped[bool] = mapped_column(default=False)
    acknowledged_by: Mapped[str | None] = mapped_column()
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    notified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AlertSubscriber(Base):
    """Подписчик рассылки в Telegram: один chat_id — одна роль."""

    __tablename__ = "alert_subscriber"
    __table_args__ = (CheckConstraint(f"role IN {ROLES!r}", name="ck_alert_subscriber_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(unique=True)
    role: Mapped[str] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True)
