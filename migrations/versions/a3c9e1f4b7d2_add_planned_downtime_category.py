"""add planned_downtime category to deferred_production

Revision ID: a3c9e1f4b7d2
Revises: ee1a92606236
Create Date: 2026-09-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a3c9e1f4b7d2'
down_revision: Union[str, Sequence[str], None] = 'ee1a92606236'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('ck_deferred_production_category', 'deferred_production', type_='check')
    op.drop_constraint('ck_deferred_production_reason_matches_category', 'deferred_production', type_='check')
    op.create_check_constraint(
        'ck_deferred_production_category',
        'deferred_production',
        "category IN ('downtime', 'planned_downtime', 'rate_reduction', 'watering', 'idle_fund')",
    )
    op.create_check_constraint(
        'ck_deferred_production_reason_matches_category',
        'deferred_production',
        "(category IN ('downtime', 'planned_downtime')) = (reason_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # deferred_production целиком пересчитывается из исходных данных
    # (deferred_runner.run_period), поэтому при откате плановые строки просто
    # удаляются — слияние в downtime могло бы упереться в уникальный индекс
    op.execute("DELETE FROM deferred_production WHERE category = 'planned_downtime'")
    op.drop_constraint('ck_deferred_production_category', 'deferred_production', type_='check')
    op.drop_constraint('ck_deferred_production_reason_matches_category', 'deferred_production', type_='check')
    op.create_check_constraint(
        'ck_deferred_production_category',
        'deferred_production',
        "category IN ('downtime', 'rate_reduction', 'watering', 'idle_fund')",
    )
    op.create_check_constraint(
        'ck_deferred_production_reason_matches_category',
        'deferred_production',
        "(category = 'downtime') = (reason_id IS NOT NULL)",
    )
