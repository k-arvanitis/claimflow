# Persistence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `Package.result_json` blob with normalized SQLite tables so reviewer corrections, extracted fields, validation failures, policy evidence, and decisions are queryable rows — not just JSON dumped into one column — without breaking the existing `POST /claims` / `GET /claims/{id}` contract.

**Architecture:** Add seven new SQLAlchemy ORM models to `src/claimflow/db.py` alongside the existing `Package` and `AuditLogEntry`. Add plain functions (one per entity, taking an explicit `Session`) that insert rows from the graph's `ClaimState` result dict. Call these from `api/main.py`'s `_run_claim` right after the existing `db.update_package_status(...)` call, so the JSON blob and the normalized rows are written from the same background task, in the same run. No migration framework — `Base.metadata.create_all` is additive and already runs on every `init_db()` call.

**Tech Stack:** SQLAlchemy 2.0 ORM (already in use), SQLite (already in use, per user decision — no move to Postgres), pytest with an in-memory SQLite engine for test isolation.

## Global Constraints

- SQLite only. No Postgres, no alembic, no new infra — `Base.metadata.create_all(engine)` handles additive schema changes for this demo-scale project.
- Do not touch `Package.result_json` or the `GET /claims/{package_id}` response shape — that stays as today's contract; the new tables are additive. Item 3 (API expansion) replaces the blob-reading endpoint later, not this plan.
- Do not rename `AuditLogEntry` — it already fulfills the spec's `AuditEvent` role (actor, action, timestamp, package_id, detail_json). Renaming a working, tested table for naming purity is unnecessary churn.
- `ReviewAction` and `Decision` are insert-only. Never update or overwrite a row — every review action and every decision is a new row, so the original machine value and every correction remain in history. This is the literal requirement from item 4 ("do not store only the latest corrected value").
- JSON-valued columns are `Text` populated via `json.dumps(...)`, matching the existing `result_json` / `detail_json` pattern already in `db.py` — no new serialization convention.
- Every new write function takes an explicit `Session` parameter (no hidden global state), matching `create_package` / `update_package_status` / `log_audit`'s existing signature style.

---

## File Structure

- **Modify: `src/claimflow/db.py`** — add 7 ORM classes (`Document`, `ExtractionRun`, `ExtractedField`, `ValidationFailure`, `PolicyEvidence`, `Decision`, `ReviewAction`) and their write functions, plus one orchestration function `persist_extraction_result` that fans a `ClaimState`-shaped result dict out into all of them.
- **Modify: `api/main.py`** — call `db.persist_extraction_result(...)` from `_run_claim` after the graph invocation succeeds.
- **Create: `tests/test_db.py`** — unit tests for every new model and write function, using an isolated in-memory SQLite engine (never touches the real `data/claimflow.db`).
- **Modify: `tests/test_api.py`** — extend the existing `test_post_claims_returns_decision` fixture data so the persistence path has non-empty documents/fields/failures/policy_answers to write, and assert the normalized rows exist after the call.

---

## Task 1: Add the 7 ORM models to `db.py`

**Files:**
- Modify: `src/claimflow/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `Base` (existing `DeclarativeBase` subclass in `db.py`), `Package` (existing, for the FK target `packages.id`).
- Produces: ORM classes `Document`, `ExtractionRun`, `ExtractedField`, `ValidationFailure`, `PolicyEvidence`, `Decision`, `ReviewAction` — used by Task 2's write functions and Task 3's tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_all_tables_created():
    session = _make_session()
    inspector_tables = db.Base.metadata.tables.keys()
    expected = {
        "packages", "audit_log", "documents", "extraction_runs",
        "extracted_fields", "validation_failures", "policy_evidence",
        "decisions", "review_actions",
    }
    assert expected.issubset(inspector_tables)
    session.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_all_tables_created -v`
Expected: FAIL with `AssertionError` (new table names missing from `db.Base.metadata.tables`).

- [ ] **Step 3: Write the ORM models**

Add to `src/claimflow/db.py`, after the existing `AuditLogEntry` class (around line 38, before `def _make_engine():`):

```python
from sqlalchemy import Boolean, Float, Integer


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    path: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String)
    has_text_layer: Mapped[bool] = mapped_column(Boolean)
    scan_quality: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    schema_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # pass|review|error
    overall_confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id"))
    name: Mapped[str] = mapped_column(String)
    value_json: Mapped[str | None] = mapped_column(Text, default=None)
    confidence: Mapped[float] = mapped_column(Float)
    grounded: Mapped[bool] = mapped_column(Boolean)
    valid: Mapped[bool] = mapped_column(Boolean)
    field_status: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[str | None] = mapped_column(Text, default=None)


class ValidationFailure(Base):
    __tablename__ = "validation_failures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id"))
    field: Mapped[str] = mapped_column(String)
    rule: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class PolicyEvidence(Base):
    __tablename__ = "policy_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    decision: Mapped[str] = mapped_column(String)  # approved|flagged|escalated
    review_reasons_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id"))
    field_name: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)  # approve|edit|reject
    original_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    corrected_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    validation_before_json: Mapped[str | None] = mapped_column(Text, default=None)
    validation_after_json: Mapped[str | None] = mapped_column(Text, default=None)
    reviewer: Mapped[str] = mapped_column(String, default="reviewer")
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
```

Add `Integer` isn't actually needed (autoincrement ints use plain `int` mapping already used by `AuditLogEntry.id`) — drop that import, only add `Boolean` and `Float`:

```python
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, create_engine
```

(replaces the existing import line at the top of `db.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::test_all_tables_created -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claimflow/db.py tests/test_db.py
git commit -m "feat: add persistence models for extraction runs, fields, and reviews"
```

---

## Task 2: Write functions for Document, ExtractionRun, ExtractedField, ValidationFailure

**Files:**
- Modify: `src/claimflow/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `Document`, `ExtractionRun`, `ExtractedField`, `ValidationFailure` from Task 1.
- Produces: `create_document(session, package_id, doc) -> Document`, `create_extraction_run(session, document_id, schema_name, status, overall_confidence) -> ExtractionRun`, `create_extracted_fields(session, extraction_run_id, fields) -> list[ExtractedField]`, `create_validation_failures(session, extraction_run_id, failures) -> list[ValidationFailure]` — all consumed by Task 4's orchestration function.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py (append)
import uuid


def test_create_document_and_extraction_run():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    doc = db.create_document(session, pkg.id, {
        "path": "/tmp/claim.pdf", "doc_type": "cms1500",
        "has_text_layer": True, "scan_quality": None,
    })
    assert doc.package_id == pkg.id
    assert doc.doc_type == "cms1500"

    run = db.create_extraction_run(session, doc.id, "cms1500", "pass", 0.91)
    assert run.document_id == doc.id
    assert run.status == "pass"

    fields = db.create_extracted_fields(session, run.id, [
        {"name": "patient_name", "value": "DOE JOHN", "confidence": 0.95,
         "grounded": True, "valid": True, "field_status": "found", "evidence": None},
    ])
    assert len(fields) == 1
    assert fields[0].extraction_run_id == run.id
    assert json.loads(fields[0].value_json) == "DOE JOHN"

    failures = db.create_validation_failures(session, run.id, [
        {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "'XXXXX' is not a recognized ICD-10-CM code"},
    ])
    assert len(failures) == 1
    assert failures[0].rule == "icd10_lookup"
    session.close()
```

Add `import json` and `import uuid` to the top of `tests/test_db.py` if not already present from Step 1 of Task 1 (only `uuid` is new here; add `import json` too since Task 1's test doesn't need it).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_create_document_and_extraction_run -v`
Expected: FAIL with `AttributeError: module 'claimflow.db' has no attribute 'create_document'`

- [ ] **Step 3: Write the functions**

Add to `src/claimflow/db.py`, after `log_audit`:

```python
def create_document(session: Session, package_id: str, doc: dict) -> Document:
    row = Document(
        id=str(uuid.uuid4()),
        package_id=package_id,
        path=doc["path"],
        doc_type=doc["doc_type"],
        has_text_layer=doc["has_text_layer"],
        scan_quality=doc.get("scan_quality"),
    )
    session.add(row)
    session.commit()
    return row


def create_extraction_run(
    session: Session, document_id: str, schema_name: str, status: str, overall_confidence: float
) -> ExtractionRun:
    row = ExtractionRun(
        id=str(uuid.uuid4()),
        document_id=document_id,
        schema_name=schema_name,
        status=status,
        overall_confidence=overall_confidence,
    )
    session.add(row)
    session.commit()
    return row


def create_extracted_fields(session: Session, extraction_run_id: str, fields: list[dict]) -> list[ExtractedField]:
    rows = [
        ExtractedField(
            extraction_run_id=extraction_run_id,
            name=f["name"],
            value_json=json.dumps(f["value"]),
            confidence=f["confidence"],
            grounded=f["grounded"],
            valid=f["valid"],
            field_status=f["field_status"],
            evidence_json=json.dumps(f["evidence"]) if f.get("evidence") is not None else None,
        )
        for f in fields
    ]
    session.add_all(rows)
    session.commit()
    return rows


def create_validation_failures(
    session: Session, extraction_run_id: str, failures: list[dict]
) -> list[ValidationFailure]:
    rows = [
        ValidationFailure(extraction_run_id=extraction_run_id, field=f["field"], rule=f["rule"], reason=f["reason"])
        for f in failures
    ]
    session.add_all(rows)
    session.commit()
    return rows
```

Add `import uuid` to the top of `src/claimflow/db.py` (it currently only imports `json`, `datetime`, `Path` — `uuid` is new).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/claimflow/db.py tests/test_db.py
git commit -m "feat: add write functions for documents, extraction runs, and fields"
```

---

## Task 3: Write functions for PolicyEvidence and Decision

**Files:**
- Modify: `src/claimflow/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `PolicyEvidence`, `Decision` from Task 1.
- Produces: `create_policy_evidence(session, package_id, answers) -> list[PolicyEvidence]`, `create_decision(session, package_id, decision, review_reasons) -> Decision` — consumed by Task 4's orchestration function.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py (append)
def test_create_policy_evidence_and_decision():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    evidence = db.create_policy_evidence(session, pkg.id, [
        {"question": "Is diagnosis code XXXXX billable?", "answer": "No, it is not a recognized code.",
         "citations": ["policy excerpt [1]"]},
    ])
    assert len(evidence) == 1
    assert json.loads(evidence[0].citations_json) == ["policy excerpt [1]"]

    decision = db.create_decision(session, pkg.id, "flagged", ["diagnosis_codes: not a recognized code"])
    assert decision.decision == "flagged"
    assert json.loads(decision.review_reasons_json) == ["diagnosis_codes: not a recognized code"]
    session.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_create_policy_evidence_and_decision -v`
Expected: FAIL with `AttributeError: module 'claimflow.db' has no attribute 'create_policy_evidence'`

- [ ] **Step 3: Write the functions**

Add to `src/claimflow/db.py`, after `create_validation_failures`:

```python
def create_policy_evidence(session: Session, package_id: str, answers: list[dict]) -> list[PolicyEvidence]:
    rows = [
        PolicyEvidence(
            package_id=package_id, question=a["question"], answer=a["answer"],
            citations_json=json.dumps(a["citations"]),
        )
        for a in answers
    ]
    session.add_all(rows)
    session.commit()
    return rows


def create_decision(session: Session, package_id: str, decision: str, review_reasons: list[str]) -> Decision:
    row = Decision(package_id=package_id, decision=decision, review_reasons_json=json.dumps(review_reasons))
    session.add(row)
    session.commit()
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add src/claimflow/db.py tests/test_db.py
git commit -m "feat: add write functions for policy evidence and decisions"
```

---

## Task 4: `record_review_action` + orchestration function `persist_extraction_result`

**Files:**
- Modify: `src/claimflow/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: all write functions from Tasks 2–3, `ReviewAction` from Task 1.
- Produces: `record_review_action(session, extraction_run_id, field_name, action, *, original_value=None, corrected_value=None, validation_before=None, validation_after=None, reviewer="reviewer", note=None) -> ReviewAction` and `persist_extraction_result(session, package_id, result: dict) -> None` — the second is called directly from `api/main.py` in Task 5. `record_review_action` has no caller yet (the review endpoint is a separate, later item) but is exercised directly by this task's test — it exists now so the schema is complete per the spec, and the future review endpoint only has to call it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py (append)
def test_record_review_action_keeps_original_and_corrected_separate():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    doc = db.create_document(session, pkg.id, {
        "path": "/tmp/claim.pdf", "doc_type": "cms1500", "has_text_layer": True, "scan_quality": None,
    })
    run = db.create_extraction_run(session, doc.id, "cms1500", "review", 0.6)

    action = db.record_review_action(
        session, run.id, "diagnosis_codes", "edit",
        original_value=["XXXXX"], corrected_value=["J06.9"],
        validation_before=["'XXXXX' is not a recognized ICD-10-CM code"],
        validation_after=[],
        reviewer="jane.reviewer",
        note="Corrected after checking the source document.",
    )
    assert action.action == "edit"
    assert json.loads(action.original_value_json) == ["XXXXX"]
    assert json.loads(action.corrected_value_json) == ["J06.9"]
    assert json.loads(action.validation_before_json) == ["'XXXXX' is not a recognized ICD-10-CM code"]
    assert json.loads(action.validation_after_json) == []
    assert action.reviewer == "jane.reviewer"
    session.close()


def test_persist_extraction_result_writes_all_rows():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    result = {
        "domain": "cms1500",
        "documents": [{"path": "/tmp/claim.pdf", "doc_type": "cms1500", "has_text_layer": True, "scan_quality": None}],
        "extraction_status": "review",
        "extraction_overall_confidence": 0.6,
        "extraction_fields": [
            {"name": "diagnosis_codes", "value": ["XXXXX"], "confidence": 0.5,
             "grounded": True, "valid": False, "field_status": "found", "evidence": None},
        ],
        "validation_failures": [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "'XXXXX' is not a recognized ICD-10-CM code"},
        ],
        "policy_answers": [
            {"question": "Is diagnosis code XXXXX billable?", "answer": "No.", "citations": ["policy excerpt [1]"]},
        ],
        "decision": "flagged",
        "review_reasons": ["diagnosis_codes: 'XXXXX' is not a recognized ICD-10-CM code"],
    }

    db.persist_extraction_result(session, pkg.id, result)

    assert session.query(db.Document).filter_by(package_id=pkg.id).count() == 1
    assert session.query(db.ExtractionRun).count() == 1
    assert session.query(db.ExtractedField).count() == 1
    assert session.query(db.ValidationFailure).count() == 1
    assert session.query(db.PolicyEvidence).filter_by(package_id=pkg.id).count() == 1
    assert session.query(db.Decision).filter_by(package_id=pkg.id).count() == 1
    session.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_record_review_action_keeps_original_and_corrected_separate tests/test_db.py::test_persist_extraction_result_writes_all_rows -v`
Expected: FAIL with `AttributeError: module 'claimflow.db' has no attribute 'record_review_action'`

- [ ] **Step 3: Write the functions**

Add to `src/claimflow/db.py`, after `create_decision`:

```python
def record_review_action(
    session: Session,
    extraction_run_id: str,
    field_name: str,
    action: str,
    *,
    original_value=None,
    corrected_value=None,
    validation_before: list | None = None,
    validation_after: list | None = None,
    reviewer: str = "reviewer",
    note: str | None = None,
) -> ReviewAction:
    row = ReviewAction(
        extraction_run_id=extraction_run_id,
        field_name=field_name,
        action=action,
        original_value_json=json.dumps(original_value) if original_value is not None else None,
        corrected_value_json=json.dumps(corrected_value) if corrected_value is not None else None,
        validation_before_json=json.dumps(validation_before) if validation_before is not None else None,
        validation_after_json=json.dumps(validation_after) if validation_after is not None else None,
        reviewer=reviewer,
        note=note,
    )
    session.add(row)
    session.commit()
    return row


def persist_extraction_result(session: Session, package_id: str, result: dict) -> None:
    """Fan a ClaimState-shaped result dict out into normalized rows.

    Additive alongside `update_package_status`'s `result_json` blob — this does not
    replace the existing GET /claims/{id} contract, it makes the same data queryable.
    """
    documents = result.get("documents") or []
    if not documents:
        return

    domain = result.get("domain")
    doc_rows = [create_document(session, package_id, doc) for doc in documents]

    claim_doc_row = next((d for d, src in zip(doc_rows, documents) if src["doc_type"] == domain), None)
    if claim_doc_row is None:
        return

    run = create_extraction_run(
        session, claim_doc_row.id, domain or "unknown",
        result.get("extraction_status") or "error",
        result.get("extraction_overall_confidence") or 0.0,
    )

    if result.get("extraction_fields"):
        create_extracted_fields(session, run.id, result["extraction_fields"])
    if result.get("validation_failures"):
        create_validation_failures(session, run.id, result["validation_failures"])
    if result.get("policy_answers"):
        create_policy_evidence(session, package_id, result["policy_answers"])
    if result.get("decision"):
        create_decision(session, package_id, result["decision"], result.get("review_reasons") or [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/claimflow/db.py tests/test_db.py
git commit -m "feat: add review action recording and result persistence orchestration"
```

---

## Task 5: Wire `persist_extraction_result` into the API background task

**Files:**
- Modify: `api/main.py:42-74` (`_run_claim`)
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `db.persist_extraction_result(session, package_id, result)` from Task 4.
- Produces: nothing new for later tasks — this is the integration point where the plan's work becomes live in the running API.

- [ ] **Step 1: Write the failing test**

Extend the existing fixture in `tests/test_api.py` so it has non-empty extraction data to persist, and assert the normalized rows exist afterward:

```python
# tests/test_api.py — replace test_post_claims_returns_decision with this version
def test_post_claims_returns_decision():
    fake_result = {
        "package_dir": "/tmp/test",
        "domain": "cms1500",
        "documents": [{"path": "/tmp/test/claim.pdf", "doc_type": "cms1500", "has_text_layer": True, "scan_quality": None}],
        "extraction_data": {"patient_name": "DOE JOHN"},
        "extraction_fields": [
            {"name": "patient_name", "value": "DOE JOHN", "confidence": 0.95,
             "grounded": True, "valid": True, "field_status": "found", "evidence": None},
        ],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.88,
        "validation_failures": [],
        "policy_answers": [],
        "decision": "approved",
        "review_reasons": [],
        "error": None,
    }

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = fake_result

    with patch("api.main.build_graph", return_value=mock_graph):
        from api.main import app
        from claimflow import db
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/claims",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            assert response.status_code == 200
            queued = response.json()
            package_id = queued["package_id"]

            result = client.get(f"/claims/{package_id}")

    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "completed"
    assert data["result"]["decision"] == "approved"

    session = db.SessionLocal()
    try:
        assert session.query(db.Document).filter_by(package_id=package_id).count() == 1
        assert session.query(db.ExtractionRun).count() == 1
        assert session.query(db.ExtractedField).count() == 1
    finally:
        session.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_post_claims_returns_decision -v`
Expected: FAIL — the `session.query(db.Document)...` assertions raise (no rows written yet, `_run_claim` never calls the new persistence function).

- [ ] **Step 3: Wire it in**

In `api/main.py`, modify `_run_claim` (currently lines 42-74):

```python
def _run_claim(graph, package_id: str, pkg_dir: Path) -> None:
    session = db.SessionLocal()
    try:
        db.update_package_status(session, package_id, "processing")
        db.log_audit(session, package_id, "api", "extract")

        thread_id = str(uuid.uuid4())
        state = {"package_dir": str(pkg_dir), "domain": None}
        config = {
            "callbacks": get_callback(),
            "configurable": {"thread_id": thread_id},
        }
        result = graph.invoke(state, config=config)

        response = {
            "decision": result.get("decision"),
            "domain": result.get("domain"),
            "documents": result.get("documents", []),
            "ocr_log": result.get("ocr_log", []),
            "extraction_overall_confidence": result.get("extraction_overall_confidence"),
            "extraction_fields": result.get("extraction_fields", []),
            "validation_failures": result.get("validation_failures", []),
            "policy_answers": result.get("policy_answers", []),
            "review_reasons": result.get("review_reasons", []),
            "error": result.get("error"),
        }
        db.log_audit(session, package_id, "api", "validate", {"validation_failures": response["validation_failures"]})
        db.update_package_status(session, package_id, "failed" if response["error"] else "completed", result=response)
        if not response["error"]:
            db.persist_extraction_result(session, package_id, result)
    except Exception as exc:
        logger.error("Background claim processing failed: %s", exc, exc_info=True)
        db.update_package_status(session, package_id, "failed", error=str(exc))
    finally:
        session.close()
```

(Only the two lines `if not response["error"]: db.persist_extraction_result(session, package_id, result)` are new, added right after the existing `db.update_package_status(...)` call.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (both `test_health` and `test_post_claims_returns_decision`)

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: All tests pass, no regressions in `test_graph.py`, `test_validate.py`, `test_new_domains.py`, `test_real_public_eval.py`.

- [ ] **Step 6: Commit**

```bash
git add api/main.py tests/test_api.py
git commit -m "feat: persist extraction results to normalized tables on claim processing"
```

---

## Self-Review Notes

- **Spec coverage:** all 9 entities from item 4 are modeled (`Package`, `Document`, `ExtractionRun`, `ExtractedField`, `ValidationFailure`, `ReviewAction`, `PolicyEvidence`, `Decision`, `AuditEvent` via existing `AuditLogEntry`). Original vs. corrected value kept separate in `ReviewAction` (`original_value_json` / `corrected_value_json`, never merged). `ReviewAction` has no caller yet — intentional, it's exercised directly by Task 4's test; wiring a review endpoint to call it is item 3/7's job, not this plan's.
- **Not in this plan:** the package/document/review/evidence/audit HTTP endpoints (item 3) and the classification override endpoint (item 7) — both build on top of this persistence layer but are separate plans per the user's chosen sequencing.
- **Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.
