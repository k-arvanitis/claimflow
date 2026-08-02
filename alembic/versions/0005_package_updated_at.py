"""package updated_at column

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13 08:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('packages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE packages SET updated_at = created_at WHERE updated_at IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('packages', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
