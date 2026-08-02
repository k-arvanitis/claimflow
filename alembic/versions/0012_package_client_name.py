"""add client_name/client_key to packages, backfill from existing extracted fields

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-02

"""
import json
import re
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors Domain.client_name_field in src/claimflow/domains/*.py at the time this
# migration was written — duplicated rather than imported so this migration keeps
# working even if the app's domain registry changes later.
_CLIENT_NAME_FIELD_BY_SCHEMA = {
    "cms1500": "patient_name",
    "eob": "patient_name",
    "medicare_summary_notice": "patient_name",
    "xactimate": "insured_name",
    "declarations_page": "insured_name",
    "loan": "applicant_name",
    "sba_form_413": "applicant_name",
}


def _client_key(name: str | None) -> str | None:
    if not name:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return normalized or None


def upgrade() -> None:
    with op.batch_alter_table("packages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("client_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("client_key", sa.String(), nullable=True))
        batch_op.create_index("ix_packages_client_key", ["client_key"])

    conn = op.get_bind()
    package_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM packages"))]
    for package_id in package_ids:
        run = conn.execute(
            sa.text(
                """
                SELECT er.id, er.schema_name
                FROM extraction_runs er
                JOIN documents d ON er.document_id = d.id
                WHERE d.package_id = :package_id
                ORDER BY er.created_at DESC
                LIMIT 1
                """
            ),
            {"package_id": package_id},
        ).first()
        if run is None:
            continue
        run_id, schema_name = run
        field_name = _CLIENT_NAME_FIELD_BY_SCHEMA.get(schema_name)
        if field_name is None:
            continue
        field = conn.execute(
            sa.text(
                """
                SELECT value_json FROM extracted_fields
                WHERE extraction_run_id = :run_id AND name = :field_name
                LIMIT 1
                """
            ),
            {"run_id": run_id, "field_name": field_name},
        ).first()
        if field is None or field[0] is None:
            continue
        value = json.loads(field[0])
        if not isinstance(value, str) or not value:
            continue
        conn.execute(
            sa.text("UPDATE packages SET client_name = :name, client_key = :key WHERE id = :id"),
            {"name": value, "key": _client_key(value), "id": package_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("packages", schema=None) as batch_op:
        batch_op.drop_index("ix_packages_client_key")
        batch_op.drop_column("client_key")
        batch_op.drop_column("client_name")
