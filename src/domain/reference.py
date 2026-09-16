"""Справочники, заполняемые сидами: причины простоя, виды ГТМ, теги измерений."""

from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class DowntimeReason(Base):
    """Классификатор причин простоя, иерархический (категория → причина).

    parent_id = NULL — это категория верхнего уровня (отказ оборудования,
    плановый ремонт, внешние причины, технологические, организационные,
    ГТМ, консервация); с parent_id — конкретная причина внутри категории.
    """

    __tablename__ = "downtime_reason"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("downtime_reason.id"))
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column()


class GtmType(Base):
    """Вид геолого-технического мероприятия (ГРП, ОПЗ, смена насоса и т.д.)."""

    __tablename__ = "gtm_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column()


class MeasurementTag(Base):
    """Справочник тегов телеметрии с единицами измерения и допустимым диапазоном.

    min_value/max_value используются модулем валидации (src/calc) как
    физически допустимые границы значения тега.
    """

    __tablename__ = "measurement_tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column()
    unit: Mapped[str | None] = mapped_column()
    min_value: Mapped[float | None] = mapped_column()
    max_value: Mapped[float | None] = mapped_column()
