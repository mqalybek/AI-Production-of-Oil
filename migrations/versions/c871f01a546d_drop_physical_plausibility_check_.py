"""drop physical-plausibility check constraints on well_test

well_test хранит сырые замеры АГЗУ до валидации (для этого есть
is_valid/validation_flags) — БД не должна отказывать в записи физически
невозможного значения, это задача модуля валидации (src/calc), а не CHECK.
Структурное ограничение (ts_end > ts_start) остаётся.

Revision ID: c871f01a546d
Revises: af0d9a143175
Create Date: 2026-09-16 11:53:13.212286

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c871f01a546d'
down_revision: Union[str, Sequence[str], None] = 'af0d9a143175'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DROPPED_CONSTRAINTS = [
    "ck_well_test_q_liquid_nonneg",
    "ck_well_test_q_oil_nonneg",
    "ck_well_test_q_water_nonneg",
    "ck_well_test_q_gas_nonneg",
    "ck_well_test_water_cut_range",
    "ck_well_test_gor_nonneg",
]

# те же значения, что были заданы при создании ограничений в af0d9a143175 —
# нужны для downgrade
_CONSTRAINT_DEFINITIONS = {
    "ck_well_test_q_liquid_nonneg": "q_liquid >= 0",
    "ck_well_test_q_oil_nonneg": "q_oil >= 0",
    "ck_well_test_q_water_nonneg": "q_water >= 0",
    "ck_well_test_q_gas_nonneg": "q_gas IS NULL OR q_gas >= 0",
    "ck_well_test_water_cut_range": "water_cut IS NULL OR water_cut BETWEEN 0 AND 100",
    "ck_well_test_gor_nonneg": "gor IS NULL OR gor >= 0",
}


def upgrade() -> None:
    """Upgrade schema."""
    for name in _DROPPED_CONSTRAINTS:
        op.drop_constraint(name, "well_test", type_="check")


def downgrade() -> None:
    """Downgrade schema."""
    for name, definition in _CONSTRAINT_DEFINITIONS.items():
        op.create_check_constraint(name, "well_test", definition)
