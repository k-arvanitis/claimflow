"""add field and rule to policy_evidence

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("policy_evidence", schema=None) as batch_op:
        batch_op.add_column(sa.Column("field", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("rule", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("policy_evidence", schema=None) as batch_op:
        batch_op.drop_column("rule")
        batch_op.drop_column("field")
