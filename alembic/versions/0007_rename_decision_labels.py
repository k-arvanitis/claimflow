"""rename decision labels to safe routing vocabulary

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_RENAME = {
    "approved": "ready_for_processing",
    "flagged": "needs_review",
    "escalated": "blocked_or_incomplete",
}


def upgrade() -> None:
    conn = op.get_bind()
    decisions = sa.table("decisions", sa.column("decision", sa.String))
    for old, new in _RENAME.items():
        conn.execute(decisions.update().where(decisions.c.decision == old).values(decision=new))


def downgrade() -> None:
    conn = op.get_bind()
    decisions = sa.table("decisions", sa.column("decision", sa.String))
    for old, new in _RENAME.items():
        conn.execute(decisions.update().where(decisions.c.decision == new).values(decision=old))
