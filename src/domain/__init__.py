"""Доменные модели. Импорт модулей ниже нужен, чтобы все таблицы
зарегистрировались в Base.metadata — на это опирается Alembic autogenerate.
"""

from src.domain.base import Base
from src.domain import (  # noqa: F401
    alerts,
    api_access,
    ingestion_log,
    master_data,
    monthly_production,
    reference,
    timeseries,
)

__all__ = ["Base"]
