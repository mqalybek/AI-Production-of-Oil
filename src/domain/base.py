"""Базовый класс декларативных моделей и engine/session БД."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
