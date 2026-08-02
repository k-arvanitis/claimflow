"""add source and is_override to decisions

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("decisions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(), nullable=False, server_default="system")
        )
        batch_op.add_column(
            sa.Column(
                "is_override", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("decisions", schema=None) as batch_op:
        batch_op.drop_column("is_override")
        batch_op.drop_column("source")
