"""Слой доступа: пользователи API (JWT-логин) и план добычи (для
сравнения факт/план на сводных экранах). Имя файла api_access, а не api,
чтобы не конфликтовать с пакетом src/api.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base

API_USER_ROLES = ("geologist", "mechanic", "manager", "admin")


class ApiUser(Base):
    """Локальный пользователь для входа в API. Пароль хранится только как
    bcrypt-хеш (см. src/api/security.py). Позже заменяется на LDAP/SSO —
    таблица сделана простой специально под замену.
    """

    __tablename__ = "api_user"
    __table_args__ = (CheckConstraint(f"role IN {API_USER_ROLES!r}", name="ck_api_user_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str] = mapped_column()
    role: Mapped[str] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True)


class ProductionPlan(Base):
    """План добычи нефти по месторождению на месяц. Заполняется вручную
    (план всегда спускается сверху/от министерства, не считается моделью).
    """

    __tablename__ = "production_plan"
    __table_args__ = (UniqueConstraint("field_id", "period_month", name="uq_production_plan_field_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("field.id"))
    period_month: Mapped[dt.date] = mapped_column(Date)
    planned_oil_t: Mapped[float] = mapped_column()
