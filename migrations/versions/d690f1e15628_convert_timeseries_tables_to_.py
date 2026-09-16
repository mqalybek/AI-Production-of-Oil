"""convert timeseries tables to timescaledb hypertables

Revision ID: d690f1e15628
Revises: 78751628ae84
Create Date: 2026-09-16 11:31:20.811594

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd690f1e15628'
down_revision: Union[str, Sequence[str], None] = '78751628ae84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Таблица -> (столбец времени, интервал чанка).
# measurement — самый плотный поток (потенциально минутная/часовая телеметрия),
# поэтому чанки по 1 дню. Остальные таймсерии — суточная/событийная гранулярность,
# чанков хватает по 1 месяцу.
HYPERTABLES = {
    "measurement": ("ts", "1 day"),
    "well_test": ("ts_start", "1 month"),
    "daily_production": ("date", "1 month"),
    "node_production": ("date", "1 month"),
    "downtime": ("ts_start", "1 month"),
    "gtm_event": ("event_date", "1 month"),
    "lab_analysis": ("ts", "1 month"),
}


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    for table, (time_column, chunk_interval) in HYPERTABLES.items():
        op.execute(
            f"SELECT create_hypertable("
            f"'{table}', '{time_column}', "
            f"chunk_time_interval => INTERVAL '{chunk_interval}', "
            f"migrate_data => TRUE)"
        )

    # Сжатие — только для measurement: самый большой объём, значения по
    # (well_id, tag_id) редко меняются задним числом старше месяца.
    # compress_segmentby группирует чанк по скважине и тегу, чтобы запросы
    # "история тега по скважине" оставались быстрыми и после сжатия.
    op.execute(
        "ALTER TABLE measurement SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'well_id, tag_id', "
        "timescaledb.compress_orderby = 'ts DESC'"
        ")"
    )
    op.execute(
        "SELECT add_compression_policy('measurement', INTERVAL '30 days')"
    )


def downgrade() -> None:
    """Downgrade schema.

    Полный откат hypertable -> обычная таблица в TimescaleDB не поддерживается
    штатно (потребовал бы пересоздания таблицы с переносом данных), поэтому
    здесь снимается только политика сжатия и режим сжатия. Сами таблицы
    остаются hypertables — это безопасно и не мешает дальнейшей работе.
    """
    op.execute(
        "SELECT remove_compression_policy('measurement', if_exists => TRUE)"
    )
    op.execute("ALTER TABLE measurement SET (timescaledb.compress = false)")
