"""Общая инфраструктура тестов: поднимает отдельную тестовую БД,
прогоняет на ней Alembic-миграции и даёт каждому тесту изолированную
транзакцию (откатывается после теста, БД между тестами не грязнится).

Миграция с переводом таблиц в TimescaleDB hypertables (d690f1e15628) сюда
не входит — она требует установленного расширения timescaledb, которого
может не быть в окружении для тестов (например, без Docker). Проверяется
отдельно, вручную, через docker-compose.
"""

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_DB_URL = "postgresql+psycopg://monitoring:monitoring@localhost:5432/production_monitoring"
TEST_DB_URL = (
    "postgresql+psycopg://monitoring:monitoring@localhost:5432/production_monitoring_test"
)

# Ревизия перед переводом в hypertables (создание таблиц, снятие физических
# CHECK на well_test, таблицы ingestion_run/ingestion_quarantine,
# allocation_method/confidence в daily_production, таблица
# deferred_production, таблицы alert/alert_subscriber, api_user/production_plan,
# monthly_production, reservoir.oil_density_t_m3/water_density_t_m3/
# density_confirmed) — см. docstring выше.
PRE_TIMESCALE_REVISION = "ee1a92606236"


def _run_alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    subprocess.run(
        [str(REPO_ROOT / ".venv" / "bin" / "alembic"), *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS production_monitoring_test"))
        conn.execute(text("CREATE DATABASE production_monitoring_test"))
    admin_engine.dispose()

    _run_alembic("upgrade", PRE_TIMESCALE_REVISION)

    yield


@pytest.fixture()
def db_session():
    """Сессия в отдельной транзакции, которая откатывается после теста.

    join_transaction_mode="create_savepoint" — если тест сам вызывает
    session.rollback() (например, после ожидаемого IntegrityError), сессия
    откатывается на SAVEPOINT, а не рвёт внешнюю транзакцию — иначе
    финальный transaction.rollback() в teardown ругался бы на то, что
    транзакция уже отсоединена от connection.
    """
    engine = create_engine(TEST_DB_URL, future=True)
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(
        bind=connection,
        future=True,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session: Session = session_factory()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()
