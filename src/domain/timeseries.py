"""Таймсерии добычи. Эти таблицы становятся TimescaleDB hypertables —
преобразование (create_hypertable, политика сжатия) делается в Alembic-миграции
отдельным шагом после создания таблиц, SQLAlchemy о hypertables не знает.

Партиционный столбец времени у каждой таблицы обязательно входит в PK —
это требование TimescaleDB.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class Measurement(Base):
    """Узкая таблица телеметрии: одно значение тега скважины на момент времени.

    Основной поток данных (потенциально минутные/часовые показания
    постоянных датчиков — Рзаб, Ртруб и т.п.), в отличие от периодических
    замеров АГЗУ (см. WellTest).
    """

    __tablename__ = "measurement"
    __table_args__ = (
        CheckConstraint("quality IN ('good', 'suspect', 'bad')", name="ck_measurement_quality"),
    )

    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("measurement_tag.id"), primary_key=True)
    value: Mapped[float] = mapped_column()
    quality: Mapped[str] = mapped_column(default="good")
    source: Mapped[str] = mapped_column()


class WellTest(Base):
    """Замер дебита на АГЗУ."""

    __tablename__ = "well_test"
    __table_args__ = (
        CheckConstraint("ts_end > ts_start", name="ck_well_test_period"),
        CheckConstraint("q_liquid >= 0", name="ck_well_test_q_liquid_nonneg"),
        CheckConstraint("q_oil >= 0", name="ck_well_test_q_oil_nonneg"),
        CheckConstraint("q_water >= 0", name="ck_well_test_q_water_nonneg"),
        CheckConstraint(
            "q_gas IS NULL OR q_gas >= 0", name="ck_well_test_q_gas_nonneg"
        ),
        CheckConstraint(
            "water_cut IS NULL OR water_cut BETWEEN 0 AND 100",
            name="ck_well_test_water_cut_range",
        ),
        CheckConstraint(
            "gor IS NULL OR gor >= 0", name="ck_well_test_gor_nonneg"
        ),
        Index("ix_well_test_well_id_ts_start", "well_id", "ts_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    ts_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ts_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    duration_h: Mapped[float] = mapped_column()
    q_liquid: Mapped[float] = mapped_column()
    q_oil: Mapped[float] = mapped_column()
    q_water: Mapped[float] = mapped_column()
    q_gas: Mapped[float | None] = mapped_column()
    water_cut: Mapped[float | None] = mapped_column()
    gor: Mapped[float | None] = mapped_column()
    p_buf: Mapped[float | None] = mapped_column()
    p_zatr: Mapped[float | None] = mapped_column()
    temperature: Mapped[float | None] = mapped_column()
    method: Mapped[str | None] = mapped_column()
    is_valid: Mapped[bool] = mapped_column(default=True)
    validation_flags: Mapped[dict | None] = mapped_column(JSONB)
    operator: Mapped[str | None] = mapped_column()


class DailyProduction(Base):
    """Суточная добыча по скважине после аллокации."""

    __tablename__ = "daily_production"
    __table_args__ = (
        CheckConstraint("q_oil_t >= 0", name="ck_daily_production_q_oil_nonneg"),
        CheckConstraint("q_liquid_t >= 0", name="ck_daily_production_q_liquid_nonneg"),
        CheckConstraint("q_water_m3 >= 0", name="ck_daily_production_q_water_nonneg"),
        CheckConstraint(
            "q_gas_m3 IS NULL OR q_gas_m3 >= 0", name="ck_daily_production_q_gas_nonneg"
        ),
        CheckConstraint(
            "hours_on BETWEEN 0 AND 24", name="ck_daily_production_hours_on_range"
        ),
        CheckConstraint("ke BETWEEN 0 AND 1", name="ck_daily_production_ke_range"),
    )

    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    q_oil_t: Mapped[float] = mapped_column()
    q_liquid_t: Mapped[float] = mapped_column()
    q_water_m3: Mapped[float] = mapped_column()
    q_gas_m3: Mapped[float | None] = mapped_column()
    hours_on: Mapped[float] = mapped_column()
    ke: Mapped[float] = mapped_column()
    allocation_factor: Mapped[float | None] = mapped_column()
    source: Mapped[str] = mapped_column()


class NodeProduction(Base):
    """Фактическая суточная добыча по узлу сбора — база для аллокации по скважинам."""

    __tablename__ = "node_production"
    __table_args__ = (
        CheckConstraint("q_oil_t >= 0", name="ck_node_production_q_oil_nonneg"),
        CheckConstraint("q_liquid_t >= 0", name="ck_node_production_q_liquid_nonneg"),
        CheckConstraint("q_water_m3 >= 0", name="ck_node_production_q_water_nonneg"),
        CheckConstraint(
            "q_gas_m3 IS NULL OR q_gas_m3 >= 0", name="ck_node_production_q_gas_nonneg"
        ),
    )

    node_id: Mapped[int] = mapped_column(ForeignKey("gathering_node.id"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    q_oil_t: Mapped[float] = mapped_column()
    q_liquid_t: Mapped[float] = mapped_column()
    q_water_m3: Mapped[float] = mapped_column()
    q_gas_m3: Mapped[float | None] = mapped_column()


class Downtime(Base):
    """Простой скважины."""

    __tablename__ = "downtime"
    __table_args__ = (
        CheckConstraint("ts_end > ts_start", name="ck_downtime_period"),
        CheckConstraint(
            "deferred_oil_t IS NULL OR deferred_oil_t >= 0",
            name="ck_downtime_deferred_oil_nonneg",
        ),
        Index("ix_downtime_well_id_ts_start", "well_id", "ts_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    ts_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ts_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    reason_id: Mapped[int] = mapped_column(ForeignKey("downtime_reason.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    deferred_oil_t: Mapped[float | None] = mapped_column()
    is_planned: Mapped[bool] = mapped_column(default=False)


class GtmEvent(Base):
    """Проведённое геолого-техническое мероприятие."""

    __tablename__ = "gtm_event"
    __table_args__ = (Index("ix_gtm_event_well_id_event_date", "well_id", "event_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    event_date: Mapped[dt.date] = mapped_column(Date)
    gtm_type_id: Mapped[int] = mapped_column(ForeignKey("gtm_type.id"))
    description: Mapped[str | None] = mapped_column(Text)
    effect_fact_t: Mapped[float | None] = mapped_column()
    effect_plan_t: Mapped[float | None] = mapped_column()


class LabAnalysis(Base):
    """Лабораторный анализ пробы (обводнённость, плотность, вязкость, состав газа)."""

    __tablename__ = "lab_analysis"
    __table_args__ = (
        CheckConstraint(
            "analysis_type IN ('water_cut', 'density', 'viscosity', 'gas_composition')",
            name="ck_lab_analysis_type",
        ),
        CheckConstraint(
            "water_cut_pct IS NULL OR water_cut_pct BETWEEN 0 AND 100",
            name="ck_lab_analysis_water_cut_range",
        ),
        CheckConstraint(
            "density_kg_m3 IS NULL OR density_kg_m3 >= 0",
            name="ck_lab_analysis_density_nonneg",
        ),
        CheckConstraint(
            "viscosity_cst IS NULL OR viscosity_cst >= 0",
            name="ck_lab_analysis_viscosity_nonneg",
        ),
        Index("ix_lab_analysis_well_id_ts", "well_id", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    analysis_type: Mapped[str] = mapped_column()
    water_cut_pct: Mapped[float | None] = mapped_column()
    density_kg_m3: Mapped[float | None] = mapped_column()
    viscosity_cst: Mapped[float | None] = mapped_column()
    gas_composition: Mapped[dict | None] = mapped_column(JSONB)
    lab_name: Mapped[str | None] = mapped_column()
    source: Mapped[str | None] = mapped_column()
