"""add status to policy_evidence

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("policy_evidence", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(), nullable=False, server_default="found")
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("policy_evidence", schema=None) as batch_op:
        batch_op.drop_column("status")
