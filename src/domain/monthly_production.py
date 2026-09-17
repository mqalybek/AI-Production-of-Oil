"""Помесячная добыча по скважине — отдельная гранулярность от
daily_production. Основной источник данных для "агента анализа добычи":
у многих компаний первичные данные — это готовые месячные цифры по
скважине (как в типовом рапорте разработки), а не суточные замеры с
телеметрией и АГЗУ. Смешивать с daily_production нельзя — разный смысл
строки (сутки vs месяц), разные агрегаты поверх неё.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base


class MonthlyProduction(Base):
    """Одна строка — одна скважина за один месяц. Дни отработки хранятся,
    т.к. по ним считается КЭ и суточный дебит, а разные компании считают
    его по-разному (календарные vs отработанные дни).

    Сознательно НЕТ CHECK на физическую правдоподобность значений (дебиты
    >= 0, обводнённость 0-100, working_days <= calendar_days) — тот же
    принцип, что и в well_test (см. ADR): источник может прислать
    физически невозможное значение (реальный файл месторождения на
    практике это подтвердил — попадаются water_cut > 100 и т.п.), это
    задача будущего слоя валидации, а не БД — отказом в записи она бы
    просто рвала загрузку всего файла из-за одной кривой строки.
    """

    __tablename__ = "monthly_production"
    __table_args__ = (
        CheckConstraint(
            "calendar_days BETWEEN 1 AND 31", name="ck_monthly_production_calendar_days_range"
        ),
        UniqueConstraint("well_id", "period_month", name="uq_monthly_production_well_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("well.id"))
    reservoir_id: Mapped[int | None] = mapped_column(ForeignKey("reservoir.id"))
    period_month: Mapped[dt.date] = mapped_column(Date)  # всегда первое число месяца
    calendar_days: Mapped[int] = mapped_column()
    working_days: Mapped[int] = mapped_column()
    q_oil_t: Mapped[float] = mapped_column()
    q_water_t: Mapped[float] = mapped_column()
    q_gas_m3: Mapped[float | None] = mapped_column()
    q_liquid_t: Mapped[float] = mapped_column()
    gor: Mapped[float | None] = mapped_column()  # газовый фактор, м3/т
    water_cut_pct: Mapped[float | None] = mapped_column()
    q_oil_rate_t_d: Mapped[float | None] = mapped_column()  # средний дебит нефти за месяц, т/сут
    source: Mapped[str] = mapped_column()  # формат/компания, из которой пришла строка
