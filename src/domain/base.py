"""Базовый класс декларативных моделей и engine/session БД."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.config import settings


class Base(DeclarativeBase):
    pass


# Соглашение проекта: время из рапортов (местное, без пояса) хранится в
# timestamptz как есть, "как будто UTC", и окна суток в расчётах тоже строятся
# в UTC — поэтому они совпадают с местными сутками. Postgres трактует время без
# пояса по TimeZone сессии, а она по умолчанию = пояс сервера (initdb берёт его
# из ОС; на промысловом сервере это будет Asia/Almaty, и всё уедет на 5 часов).
# Поэтому UTC фиксируется на уровне подключения, независимо от настроек сервера.
DB_CONNECT_ARGS = {"options": "-c timezone=UTC"}

engine = create_engine(settings.database_url, future=True, connect_args=DB_CONNECT_ARGS)
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
