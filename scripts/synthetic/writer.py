"""Запись сгенерированных данных: CSV в data/synthetic/ + bulk-вставка в БД.

Не через ORM построчно (для measurement это были бы часы) — через
SQLAlchemy Core executemany пачками.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.domain import Base

# Порядок важен: сначала независимые/справочные таблицы, потом те, что на них ссылаются.
TABLE_ORDER = [
    "downtime_reason",
    "gtm_type",
    "measurement_tag",
    "field",
    "reservoir",
    "gathering_node",
    "well",
    "well_alias",
    "completion",
    "equipment",
    "well_gathering_node_history",
    "daily_production",
    "well_test",
    "node_production",
    "downtime",
    "gtm_event",
    "measurement",
]

# Таблицы, где id проставляем сами (не полагаемся на SERIAL) — после вставки
# нужно подвинуть последовательность, иначе следующий INSERT из приложения
# столкнётся с уже занятым id.
TABLES_WITH_EXPLICIT_IDS = [
    "downtime_reason",
    "gtm_type",
    "measurement_tag",
    "field",
    "reservoir",
    "gathering_node",
    "well",
    "well_alias",
    "completion",
    "equipment",
    "well_gathering_node_history",
    "downtime",
    "gtm_event",
]


def _to_dataframe(rows: object) -> pd.DataFrame:
    return rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)


def write_csv(tables: dict[str, object], out_dir: str | Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in TABLE_ORDER:
        if name not in tables:
            continue
        _to_dataframe(tables[name]).to_csv(out_dir / f"{name}.csv", index=False)


def write_db(
    tables: dict[str, object], engine: Engine, truncate: bool = True, chunk_size: int = 20_000
) -> None:
    present = [t for t in TABLE_ORDER if t in tables]

    with engine.begin() as conn:
        if truncate:
            conn.execute(text(f"TRUNCATE TABLE {', '.join(present)} RESTART IDENTITY CASCADE"))

        for name in present:
            df = _to_dataframe(tables[name])
            if df.empty:
                continue
            sa_table = Base.metadata.tables[name]
            # .where на числовой колонке вернул бы NaN обратно (а не None) из-за
            # приведения типов — поэтому сначала переводим в object
            records = df.astype(object).where(df.notna(), None).to_dict("records")
            for start in range(0, len(records), chunk_size):
                conn.execute(sa_table.insert(), records[start : start + chunk_size])

        for name in TABLES_WITH_EXPLICIT_IDS:
            if name not in tables:
                continue
            conn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {name}), 1))"
                )
            )
