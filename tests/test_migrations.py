import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrade_head_creates_full_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parent.parent,
        env={"DB_PATH": str(db_path), **__import__("os").environ},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert {
        "packages",
        "documents",
        "extraction_runs",
        "extracted_fields",
        "validation_failures",
        "policy_evidence",
        "decisions",
        "review_actions",
        "audit_log",
    } <= tables

    columns = {c["name"] for c in inspect(engine).get_columns("validation_failures")}
    assert {"machine_value", "expected_value"} <= columns

    policy_columns = {c["name"] for c in inspect(engine).get_columns("policy_evidence")}
    assert "status" in policy_columns


def _run_alembic(repo_root, db_path, *args):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=repo_root,
        env={"DB_PATH": str(db_path), **os.environ},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_0007_rename_decision_labels_upgrade_and_downgrade(tmp_path):
    db_path = tmp_path / "migrated.db"
    repo_root = Path(__file__).resolve().parent.parent

    _run_alembic(repo_root, db_path, "upgrade", "0006")

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO packages (id, created_at, status) VALUES ('pkg-1', '2026-07-27', 'done')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO decisions (package_id, decision, review_reasons_json, created_at) "
                "VALUES ('pkg-1', 'flagged', '[]', '2026-07-27')"
            )
        )
    engine.dispose()

    _run_alembic(repo_root, db_path, "upgrade", "0007")

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT decision FROM decisions WHERE package_id = 'pkg-1'")
        ).scalar_one()
    engine.dispose()
    assert value == "needs_review"

    _run_alembic(repo_root, db_path, "downgrade", "0006")

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT decision FROM decisions WHERE package_id = 'pkg-1'")
        ).scalar_one()
    engine.dispose()
    assert value == "flagged"
