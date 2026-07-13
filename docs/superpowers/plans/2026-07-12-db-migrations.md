# Database Migrations + Integrity Constraints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ClaimFlow's `Base.metadata.create_all()`-only schema management with real Alembic migrations, enable SQLite foreign-key enforcement, add the indexes/constraints the current schema is missing, and make deletion cascades explicit and DB-enforced instead of the current hand-rolled per-table delete loop.

**Architecture:** `src/claimflow/db.py`'s SQLAlchemy models gain `index=True` on hot lookup columns, `ForeignKey(..., ondelete="CASCADE")` + `relationship(..., cascade="all, delete-orphan", passive_deletes=True)` on parent-child pairs so a single `session.delete(pkg)` cascades at the DB level, and a `UniqueConstraint` on `(Document.package_id, Document.path)`. `AuditLogEntry.package_id` deliberately loses its hard `ForeignKey` — audit history is designed to outlive the package it describes, so it becomes a plain indexed string (a documented, intentional decision, not an oversight). A new `alembic/` directory holds migration history; `api/main.py`'s startup runs `alembic upgrade head` instead of `create_all`. Tests keep using `Base.metadata.create_all()` directly against a throwaway per-test SQLite file — that's a test-fixture bootstrap, not the app's real schema-management path, so it doesn't violate "don't depend on auto-create as the only schema management."

**Tech Stack:** SQLAlchemy 2.x (already in use), Alembic (new dependency), SQLite, pytest.

## Global Constraints

- Foreign-key enforcement (`PRAGMA foreign_keys=ON`) must be active on every connection this app opens, including test connections — implement via a SQLAlchemy `Engine` "connect" event listener, not a call site the caller might forget.
- Cascade deletes are DB-enforced (`ON DELETE CASCADE` + `passive_deletes=True`), not hand-rolled per-table Python loops. `delete_package` becomes `session.delete(pkg); session.commit()`.
- `AuditLogEntry.package_id` is a plain indexed `String`, not a `ForeignKey` — audit trail rows are retained after a package is deleted. This is a deliberate design decision (confirmed with the project owner), not a gap to fix later.
- Required indexes: `Package.status`, `Package.created_at`, `ExtractedField.field_status` (the "reviewer state" column reviewers filter/sort on), `Document.package_id`. Additionally index every other foreign-key column (`ExtractionRun.document_id`, `ExtractedField.extraction_run_id`, `ValidationFailure.extraction_run_id`, `ReviewAction.extraction_run_id`, `PolicyEvidence.package_id`, `Decision.package_id`, `AuditLogEntry.package_id`) — SQLite does not auto-index FK columns, and these are exactly the columns the cascade-delete and per-package list queries filter on.
- Required uniqueness: `UniqueConstraint("package_id", "path", name="uq_document_package_path")` on `Document` — one upload of a given filename per package.
- No `Base.metadata.create_all()` in the app's real startup path (`api/main.py`'s `lifespan`) — that path must run Alembic migrations. `tests/conftest.py`'s `create_all()` against a fresh per-test SQLite file is an explicit, documented exception (test bootstrap, not app startup).
- Never delete `data/claimflow.db` — if it exists when the baseline migration is applied, rename it aside first (`data/claimflow.db.pre-migration.bak`) rather than dropping it, per data-safety practice; the app will create a fresh migrated DB at the original path.
- New dependency allowed for this plan only: `alembic`. No other new dependencies.

---

### Task 1: Schema changes — indexes, cascades, unique constraint, FK-enforcement pragma

**Files:**
- Modify: `src/claimflow/db.py` (model definitions, `delete_package`)
- Test: `tests/test_db_constraints.py`

**Interfaces:**
- Produces: `Package.documents`, `Package.policy_evidence_entries`, `Package.decisions` relationships (cascade-configured); `Document.package`, `Document.extraction_runs`; `ExtractionRun.document`, `ExtractionRun.extracted_fields`, `ExtractionRun.validation_failures`, `ExtractionRun.review_actions` — Task 2's migration autogeneration reads these definitions directly, so names must match exactly what Task 2's brief references.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from claimflow import db


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/constraints.db")
    db.Base.metadata.create_all(eng)
    return eng


def test_foreign_keys_are_enforced(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(db.Document(id="doc1", package_id="does-not-exist", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_package_cascades_to_children_but_not_audit(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(db.Package(id="pkg1", status="completed"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.add(db.ExtractionRun(id="run1", document_id="doc1", schema_name="cms1500", status="pass", overall_confidence=0.9))
    session.add(db.ExtractedField(extraction_run_id="run1", name="f", confidence=0.9, grounded=True, valid=True, field_status="found"))
    session.add(db.AuditLogEntry(package_id="pkg1", actor="api", action="upload"))
    session.commit()

    pkg = session.get(db.Package, "pkg1")
    session.delete(pkg)
    session.commit()

    assert session.get(db.Document, "doc1") is None
    assert session.get(db.ExtractionRun, "run1") is None
    assert session.query(db.ExtractedField).count() == 0
    assert session.query(db.AuditLogEntry).filter_by(package_id="pkg1").count() == 1


def test_duplicate_document_path_in_same_package_rejected(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(db.Package(id="pkg1", status="completed"))
    session.commit()
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.commit()
    session.add(db.Document(id="doc2", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_constraints.py -v`
Expected: FAIL — `test_foreign_keys_are_enforced` fails because SQLite has no FK enforcement listener yet (the insert succeeds instead of raising); `test_deleting_package_cascades_to_children_but_not_audit` fails because there's no `ON DELETE CASCADE`, so `session.delete(pkg)` alone (without the current manual loop) leaves orphaned children; `test_duplicate_document_path_in_same_package_rejected` fails because there's no unique constraint.

- [ ] **Step 3: Add the FK-enforcement event listener**

At the top of `src/claimflow/db.py`, after the existing imports, add:

```python
from sqlalchemy import event
from sqlalchemy.engine import Engine


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

- [ ] **Step 4: Update imports for relationships/constraints**

Replace the existing SQLAlchemy import line:

```python
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
```

with:

```python
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
```

(drop the separate `event`/`Engine` import added in Step 3 since it's now on this combined line — keep only one import block)

- [ ] **Step 5: Rewrite the model definitions**

Replace `src/claimflow/db.py`'s model block (from `class Package(Base):` through `class ReviewAction(Base):`'s closing field) with:

```python
class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)  # queued|processing|completed|failed
    result_json: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", passive_deletes=True
    )
    policy_evidence_entries: Mapped[list["PolicyEvidence"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", passive_deletes=True
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", passive_deletes=True
    )


class AuditLogEntry(Base):
    """package_id is intentionally NOT a ForeignKey: audit history must survive
    package deletion, so it's a plain indexed string reference, not a cascade target."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    actor: Mapped[str] = mapped_column(String)  # e.g. "api", "reviewer"
    action: Mapped[str] = mapped_column(String)  # e.g. "upload", "extract", "validate", "review_edit"
    detail_json: Mapped[str | None] = mapped_column(Text, default=None)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("package_id", "path", name="uq_document_package_path"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String)
    has_text_layer: Mapped[bool] = mapped_column(Boolean)
    scan_quality: Mapped[float | None] = mapped_column(Float, default=None)
    classification_reason: Mapped[str | None] = mapped_column(Text, default=None)
    manually_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    package: Mapped["Package"] = relationship(back_populates="documents")
    extraction_runs: Mapped[list["ExtractionRun"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    schema_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # pass|review|error
    overall_confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    document: Mapped["Document"] = relationship(back_populates="extraction_runs")
    extracted_fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan", passive_deletes=True
    )
    validation_failures: Mapped[list["ValidationFailure"]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan", passive_deletes=True
    )
    review_actions: Mapped[list["ReviewAction"]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan", passive_deletes=True
    )


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    value_json: Mapped[str | None] = mapped_column(Text, default=None)
    confidence: Mapped[float] = mapped_column(Float)
    grounded: Mapped[bool] = mapped_column(Boolean)
    valid: Mapped[bool] = mapped_column(Boolean)
    field_status: Mapped[str] = mapped_column(String, index=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, default=None)

    extraction_run: Mapped["ExtractionRun"] = relationship(back_populates="extracted_fields")


class ValidationFailure(Base):
    __tablename__ = "validation_failures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String)
    rule: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    extraction_run: Mapped["ExtractionRun"] = relationship(back_populates="validation_failures")


class PolicyEvidence(Base):
    __tablename__ = "policy_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    package: Mapped["Package"] = relationship(back_populates="policy_evidence_entries")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String)  # approved|flagged|escalated
    review_reasons_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    package: Mapped["Package"] = relationship(back_populates="decisions")


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)  # approve|edit|reject
    original_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    corrected_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    validation_before_json: Mapped[str | None] = mapped_column(Text, default=None)
    validation_after_json: Mapped[str | None] = mapped_column(Text, default=None)
    reviewer: Mapped[str] = mapped_column(String, default="reviewer")
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    extraction_run: Mapped["ExtractionRun"] = relationship(back_populates="review_actions")
```

- [ ] **Step 6: Rewrite `delete_package` to rely on the DB cascade**

Replace the current `delete_package` function (the one with the long manual per-table deletion comment and loop) with:

```python
def delete_package(session: Session, package_id: str) -> bool:
    pkg = session.get(Package, package_id)
    if pkg is None:
        return False
    session.delete(pkg)
    session.commit()
    return True
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_constraints.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Run the full existing suite to check for regressions**

Run: `uv run pytest tests/ -q`
Expected: same pass count as baseline (no new failures) — `delete_package`'s simplified body must behave identically to the old manual-loop version for every existing caller/test.

- [ ] **Step 9: Commit**

```bash
git add src/claimflow/db.py tests/test_db_constraints.py
git commit -m "feat: enforce FK constraints, DB-level cascade deletes, and document uniqueness"
```

---

### Task 2: Alembic scaffolding + baseline migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_baseline.py`
- Modify: `pyproject.toml` (add `alembic` dependency)
- Modify: `api/main.py` (`lifespan` runs migrations instead of `create_all`)
- Test: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `Base`, `Package`, `Document`, etc. from Task 1's finished `src/claimflow/db.py` — the baseline migration's schema must match Task 1's models exactly (it's generated from them).
- Produces: `alembic/env.py` importing `claimflow.db.Base` as `target_metadata` and `claimflow.config.settings.db_path` for the connection URL — later tasks (Makefile targets in Task 3) invoke this via `uv run alembic upgrade head`.

- [ ] **Step 1: Add the `alembic` dependency**

In `pyproject.toml`, add `"alembic>=1.13.0",` to the `dependencies` list (alongside `"sqlalchemy>=2.0.51",`).

Run: `uv sync`
Expected: `alembic` installed, no dependency conflicts.

- [ ] **Step 2: Initialize the Alembic scaffold**

Run: `uv run alembic init alembic`
Expected: creates `alembic.ini` and `alembic/` (with `env.py`, `script.py.mako`, `versions/`) in the repo root.

- [ ] **Step 3: Point `alembic.ini` at the app's DB path indirectly**

In `alembic.ini`, find the line `sqlalchemy.url = driver://user:pass@localhost/dbname` and delete it (the URL will be set programmatically in `env.py` from `claimflow.config.settings`, not hardcoded here, since `db_path` is configurable).

- [ ] **Step 4: Write `alembic/env.py`**

Replace the generated `alembic/env.py` with:

```python
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claimflow.config import settings
from claimflow.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_path}")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

(`render_as_batch=True` is required for SQLite — it can't `ALTER TABLE ADD CONSTRAINT` in place, Alembic works around this by rebuilding the table in a batch operation.)

- [ ] **Step 5: If a dev DB already exists, rename it aside (never delete)**

Run: `test -f data/claimflow.db && mv data/claimflow.db data/claimflow.db.pre-migration.bak || echo "no existing dev DB, nothing to rename"`

- [ ] **Step 6: Autogenerate the baseline migration**

Run: `uv run alembic revision --autogenerate -m "baseline"`
Expected: creates `alembic/versions/<hash>_baseline.py` reflecting every table/column/index/constraint from Task 1's `src/claimflow/db.py` models (since there's no existing DB at `data/claimflow.db` after Step 5, Alembic diffs against an empty DB, producing full `CREATE TABLE` statements — including the indexes, `ondelete="CASCADE"` foreign keys, and the `uq_document_package_path` unique constraint).

Rename the generated file to `alembic/versions/0001_baseline.py` for a predictable name, and update the `revision = "..."` value inside it to `"0001"` (keep `down_revision = None`).

- [ ] **Step 7: Write the failing test**

```python
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_head_creates_full_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setenv("CLAIMFLOW_DB_PATH", str(db_path))

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parent.parent,
        env={"CLAIMFLOW_DB_PATH": str(db_path), **__import__("os").environ},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert {"packages", "documents", "extraction_runs", "extracted_fields", "validation_failures", "policy_evidence", "decisions", "review_actions", "audit_log"} <= tables
```

This test requires `Settings` to read `db_path` from an env var. Check `src/claimflow/config.py` — `pydantic_settings.BaseSettings` already reads env vars matching field names case-insensitively by default (`CLAIMFLOW_DB_PATH` won't match `db_path` without a prefix). Add `env_prefix="CLAIMFLOW_"` is NOT currently set, so the actual env var FastAPI/pydantic-settings would read is `DB_PATH`, not `CLAIMFLOW_DB_PATH`. Use `monkeypatch.setenv("DB_PATH", str(db_path))` instead, and pass `env={"DB_PATH": str(db_path), **__import__("os").environ}` in the subprocess call.

- [ ] **Step 8: Run test to verify it fails**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: FAIL before Step 6/9 wiring is complete — if Step 6 already ran successfully, this test should already pass; if so, treat this as the confirming "PASS" run instead and note in your task report that the red step was implicitly covered by Step 6's manual `alembic upgrade head` verification. Either way, run it now and record the actual result.

- [ ] **Step 9: Wire `api/main.py`'s startup to run migrations instead of `create_all`**

Replace the `lifespan` function's `db.init_db()` call. First, in `src/claimflow/db.py`, replace the `init_db` function:

```python
def init_db() -> None:
    Base.metadata.create_all(engine)
```

with:

```python
def init_db() -> None:
    """Applies Alembic migrations. NOT the schema source of truth by itself —
    the migrations under alembic/versions/ are; this just runs them.
    Tests bypass this and call Base.metadata.create_all() directly against a
    throwaway per-test DB (see tests/conftest.py) for speed/isolation."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")
```

`api/main.py`'s `lifespan` already calls `db.init_db()` — no change needed there, the new implementation is a drop-in replacement.

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/test_migrations.py tests/ -q`
Expected: PASS — full suite green, including `tests/test_migrations.py`.

- [ ] **Step 11: Commit**

```bash
git add alembic.ini alembic/ pyproject.toml uv.lock src/claimflow/db.py tests/test_migrations.py
git commit -m "feat: add Alembic migrations, replace create_all with alembic upgrade head at startup"
```

---

### Task 3: Clean DB init command + Makefile targets

**Files:**
- Modify: `Makefile`
- Test: manual verification (Makefile targets aren't unit-testable in the usual sense; verify by running them)

**Interfaces:**
- Consumes: `alembic.ini` from Task 2.

- [ ] **Step 1: Add Makefile targets**

In `Makefile`, add near the `install`/`dev` targets:

```makefile
db-migrate:
	uv run alembic upgrade head

db-init: db-migrate
	@echo "Database initialized at $$(uv run python -c 'from claimflow.config import settings; print(settings.db_path)')"

db-revision:
	uv run alembic revision --autogenerate -m "$(MSG)"
```

Add `db-migrate db-init db-revision` to the `.PHONY` line at the top of the file.

- [ ] **Step 2: Verify `make db-init` works on a clean checkout**

Run:
```bash
rm -f data/claimflow.db
make db-init
```
Expected: prints `Database initialized at data/claimflow.db`, and `data/claimflow.db` exists afterward with the full migrated schema (verify with `uv run python -c "from sqlalchemy import create_engine, inspect; print(sorted(inspect(create_engine('sqlite:///data/claimflow.db')).get_table_names()))"`).

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add db-init/db-migrate/db-revision Makefile targets"
```

---

## Self-Review Notes

- **Spec coverage:** Alembic migrations (Task 2), FK enforcement (Task 1 Step 3), indexes for package status/created date/reviewer state/document package ID plus every other FK column (Task 1 Step 5), uniqueness on `Document(package_id, path)` (Task 1 Step 5), verified cascades (Task 1's tests), intentional audit-retention behavior on package delete (Task 1's design + test), clean DB init command (Task 3). Not covered by this plan: extraction-run/version tracking on reprocessing, stale-processing recovery after restart, idempotent `/process` — those are Task 3 ("harden processing state machine") in the parent TODO, a separate plan.
- **Placeholder scan:** none found.
- **Type consistency:** relationship names (`documents`, `extraction_runs`, `extracted_fields`, `validation_failures`, `review_actions`, `policy_evidence_entries`, `decisions`) are used consistently between Task 1's model definitions and are not referenced by name in Task 2/3 (which only touch migration tooling), so no cross-task drift risk.
