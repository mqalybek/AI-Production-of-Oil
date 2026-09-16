"""Доменные модели. Импорт модулей ниже нужен, чтобы все таблицы
зарегистрировались в Base.metadata — на это опирается Alembic autogenerate.
"""

from src.domain.base import Base
from src.domain import alerts, ingestion_log, master_data, reference, timeseries  # noqa: F401

__all__ = ["Base"]
