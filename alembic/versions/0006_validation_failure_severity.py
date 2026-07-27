"""add severity and policy_required to validation_failures

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("validation_failures", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("severity", sa.String(), nullable=False, server_default="error")
        )
        batch_op.add_column(
            sa.Column(
                "policy_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("validation_failures", schema=None) as batch_op:
        batch_op.drop_column("policy_required")
        batch_op.drop_column("severity")
