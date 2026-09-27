"""Время без пояса из рапортов должно ложиться в БД "как UTC" независимо от
часового пояса, выставленного на сервере Postgres (см. DB_CONNECT_ARGS)."""

import datetime as dt

from sqlalchemy import create_engine, text

from src.domain.base import DB_CONNECT_ARGS
from tests.conftest import ADMIN_DB_URL, TEST_DB_URL


def test_naive_timestamp_is_stored_as_utc_even_if_server_zone_is_local():
    admin = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("ALTER DATABASE production_monitoring_test SET timezone = 'Asia/Almaty'"))
    try:
        engine = create_engine(TEST_DB_URL, connect_args=DB_CONNECT_ARGS)
        with engine.connect() as conn:
            stored = conn.execute(
                text("SELECT CAST(:ts AS timestamptz)"), {"ts": dt.datetime(2024, 6, 1, 0, 0)}
            ).scalar_one()
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text("ALTER DATABASE production_monitoring_test RESET timezone"))
        admin.dispose()

    assert stored == dt.datetime(2024, 6, 1, 0, 0, tzinfo=dt.timezone.utc)
