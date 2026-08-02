"""add machine_value and expected_value to validation_failures

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("validation_failures", schema=None) as batch_op:
        batch_op.add_column(sa.Column("machine_value", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("expected_value", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("validation_failures", schema=None) as batch_op:
        batch_op.drop_column("expected_value")
        batch_op.drop_column("machine_value")
