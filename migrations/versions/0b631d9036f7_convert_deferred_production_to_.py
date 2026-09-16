"""convert deferred_production to timescaledb hypertable

Отдельной миграцией (не трогаем d690f1e15628) — deferred_production
появилась позже остальных таймсерий. Партиционный столбец — date, чанк
1 месяц (объём на порядки меньше measurement, как у остальных
суточных/событийных таблиц).

Revision ID: 0b631d9036f7
Revises: 1d7678e78ece
Create Date: 2026-09-16 18:44:57.765335

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0b631d9036f7'
down_revision: Union[str, Sequence[str], None] = '1d7678e78ece'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "SELECT create_hypertable("
        "'deferred_production', 'date', "
        "chunk_time_interval => INTERVAL '1 month', "
        "migrate_data => TRUE)"
    )


def downgrade() -> None:
    """Downgrade schema.

    Как и для остальных hypertables (см. d690f1e15628) — штатного отката
    hypertable -> обычная таблица нет, здесь и убирать нечего (сжатие для
    этой таблицы не включалось).
    """
    pass
