"""add allocation_method and confidence to daily_production, allocation_factor to jsonb

daily_production.allocation_factor был одним числом — теперь аллокация
ведётся по каждой фазе независимо (нефть/жидкость/вода/газ могут иметь
разные K на одном узле в одни сутки), поэтому это {"oil": K, "liquid": K,
"water": K, "gas": K}, а не скаляр. См. ADR в CLAUDE.md.

Revision ID: 98ac2912cfae
Revises: 7cc89f9232e6
Create Date: 2026-09-16 12:49:59.301041

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '98ac2912cfae'
down_revision: Union[str, Sequence[str], None] = '7cc89f9232e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('daily_production', sa.Column('allocation_method', sa.String(), nullable=True))
    op.add_column('daily_production', sa.Column('confidence', sa.String(), nullable=True))
    op.alter_column(
        'daily_production',
        'allocation_factor',
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using='to_jsonb(allocation_factor)',
    )
    op.create_check_constraint(
        'ck_daily_production_allocation_method',
        'daily_production',
        "allocation_method IS NULL OR allocation_method IN ('measured', 'extrapolated', 'analog')",
    )
    op.create_check_constraint(
        'ck_daily_production_confidence',
        'daily_production',
        "confidence IS NULL OR confidence IN ('high', 'medium', 'low')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_daily_production_confidence', 'daily_production', type_='check')
    op.drop_constraint('ck_daily_production_allocation_method', 'daily_production', type_='check')
    op.alter_column(
        'daily_production',
        'allocation_factor',
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.DOUBLE_PRECISION(precision=53),
        existing_nullable=True,
        postgresql_using="(allocation_factor->>'oil')::double precision",
    )
    op.drop_column('daily_production', 'confidence')
    op.drop_column('daily_production', 'allocation_method')
