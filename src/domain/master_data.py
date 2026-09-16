"""Мастер-данные: месторождения, скважины, оборудование, узлы сбора.

Перечисляемые поля (well_type, status и т.п.) сознательно хранятся как
VARCHAR + CHECK, а не native Postgres ENUM — добавление нового значения
(например, новой причины простоя) тогда делается обычной миграцией
ALTER TABLE ADD CONSTRAINT, без блокировок и ограничений ALTER TYPE.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class Field(Base):
    """Месторождение."""

    __tablename__ = "field"
    __table_args__ = (
        CheckConstraint("field_type IN ('oil', 'gas', 'gas_condensate')", name="ck_field_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    field_type: Mapped[str] = mapped_column()


class Reservoir(Base):
    """Объект разработки / горизонт месторождения."""

    __tablename__ = "reservoir"
    __table_args__ = (UniqueConstraint("field_id", "name", name="uq_reservoir_field_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("field.id"))
    name: Mapped[str] = mapped_column()
    horizon_code: Mapped[str | None] = mapped_column()


class Well(Base):
    """Скважина. uwi — сквозной ключ, на который ссылаются все внешние системы."""

    __tablename__ = "well"
    __table_args__ = (
        CheckConstraint(
            "well_type IN ('producer', 'injector', 'piezometric', 'water_intake')",
            name="ck_well_type",
        ),
        CheckConstraint(
            "status IN ('active', 'idle', 'mothballed', 'abandoned', 'drilling')",
            name="ck_well_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uwi: Mapped[str] = mapped_column(unique=True)
    gos_number: Mapped[str | None] = mapped_column()
    name: Mapped[str | None] = mapped_column()
    field_id: Mapped[int] = mapped_column(ForeignKey("field.id"))
    well_type: Mapped[str] = mapped_column()
    status: Mapped[str] = mapped_column()
    spud_date: Mapped[dt.date | None] = mapped_column(Date)
    wellhead_x: Mapped[float | None] = mapped_column()
    wellhead_y: Mapped[float | None] = mapped_column()
    altitude: Mapped[float | None] = mapped_column()


class WellAlias(Base):
    """Маппинг UWI на идентификаторы скважины во внешних системах (АСУ ТП, 1С, ГДМ)."""

    __tablename__ = "well_alias"
    __table_args__ = (
        UniqueConstraint("external_system", "external_id", name="uq_well_alias_external"),
        Index("ix_well_alias_well_id", "well_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    external_system: Mapped[str] = mapped_column()
    external_id: Mapped[str] = mapped_column()


class Completion(Base):
    """Интервал перфорации скважины по объекту разработки."""

    __tablename__ = "completion"
    __table_args__ = (
        CheckConstraint("bottom_md > top_md", name="ck_completion_bottom_gt_top"),
        CheckConstraint(
            "status IN ('open', 'isolated', 'closed')", name="ck_completion_status"
        ),
        Index("ix_completion_well_id", "well_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    reservoir_id: Mapped[int] = mapped_column(ForeignKey("reservoir.id"))
    top_md: Mapped[float] = mapped_column()
    bottom_md: Mapped[float] = mapped_column()
    perf_date: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column()


class Equipment(Base):
    """Подъёмное оборудование скважины (история монтажа/демонтажа)."""

    __tablename__ = "equipment"
    __table_args__ = (
        CheckConstraint(
            "equipment_type IN ('esp', 'srp', 'flowing', 'gas_lift')",
            name="ck_equipment_type",
        ),
        CheckConstraint(
            "pull_date IS NULL OR pull_date > install_date",
            name="ck_equipment_pull_after_install",
        ),
        Index("ix_equipment_well_id", "well_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    equipment_type: Mapped[str] = mapped_column()
    type_size: Mapped[str | None] = mapped_column()
    run_depth: Mapped[float | None] = mapped_column()
    install_date: Mapped[dt.date] = mapped_column(Date)
    pull_date: Mapped[dt.date | None] = mapped_column(Date)


class GatheringNode(Base):
    """Узел сбора продукции: ГУ, ДНС или АГЗУ."""

    __tablename__ = "gathering_node"
    __table_args__ = (
        CheckConstraint("node_type IN ('gu', 'dns', 'agzu')", name="ck_gathering_node_type"),
        UniqueConstraint("field_id", "name", name="uq_gathering_node_field_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("field.id"))
    name: Mapped[str] = mapped_column()
    node_type: Mapped[str] = mapped_column()


class WellGatheringNodeHistory(Base):
    """История привязки скважины к узлу сбора (скважину могут перевести на другой узел).

    valid_to = NULL означает текущую (действующую) привязку.
    """

    __tablename__ = "well_gathering_node_history"
    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_well_gathering_node_history_period",
        ),
        Index("ix_well_gathering_node_history_well_id", "well_id", "valid_from"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    node_id: Mapped[int] = mapped_column(ForeignKey("gathering_node.id"))
    valid_from: Mapped[dt.date] = mapped_column(Date)
    valid_to: Mapped[dt.date | None] = mapped_column(Date)
