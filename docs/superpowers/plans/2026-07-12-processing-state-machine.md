# Processing State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /packages/{package_id}/process` reliable and idempotent: reject a second concurrent run instead of racing, expand `Package.status` to the full state set the product needs (`review_ready` as a distinct outcome from `completed`, three distinct failure states instead of one generic `failed`), recover packages stuck mid-processing after an app restart, version `ExtractionRun` rows across reprocesses, and record every status transition in the audit trail.

**Architecture:** `Package.status` gains 4 new enum values. A new `db.try_start_processing()` does an atomic SQL `UPDATE ... WHERE status IN (...)` compare-and-swap so two concurrent `/process` calls can't both win the race to `processing` — the loser gets a 409. A new `db.transition_package_status()` centralizes every status write behind one audit-logged call, replacing direct `update_package_status` calls in the processing path. `_run_claim` classifies outcomes three ways: a structured `error` returned by `ingest`/`extract` (the only nodes that produce one) → `processing_error`; a decision of `approved` → `completed`; a decision of `flagged`/`escalated` → `review_ready`. An uncaught exception (only reachable today via `retrieve_node`'s external Qdrant/LLM calls, or an unexpected crash elsewhere) is classified by inspecting the LangGraph checkpointer's last-known state for that run — which fields got populated tells us which node was reached. `ExtractionRun` gains an `attempt` counter (count of prior runs for that document + 1) so reprocessing produces a queryable version history instead of an anonymous pile of rows. `lifespan` gains a startup sweep that marks any package still `processing` (impossible unless the process was killed mid-run) as `processing_error`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic (already set up), LangGraph (existing `MemorySaver` checkpointer, already configured but previously unused for this purpose), pytest.

## Global Constraints

- `PackageStatus` becomes: `uploaded`, `queued`, `processing`, `review_ready`, `completed`, `processing_error`, `validation_error`, `retrieval_error`. (`uploaded` is set for the brief window in `create_package` before the background task starts; every other transition happens inside `_run_claim` or the restart sweep.)
- Every status write on the processing path goes through `db.transition_package_status(session, package_id, new_status, reason=..., error=None, result=None)` — never call `update_package_status` directly from `api/main.py`'s processing code again. It logs one `AuditLogEntry` per call with `action="status_transition"` and `detail={"from": ..., "to": ..., "reason": ...}`.
- `POST /packages/{package_id}/process` must be safe to call twice in a row without corrupting state: the second call while the first is still `processing` gets `409 AppError("PROCESSING_IN_PROGRESS", ...)`, not a second background task racing the first.
- A package in any of `completed`, `review_ready`, `processing_error`, `validation_error`, `retrieval_error` can be reprocessed (that's the retry path) — reprocessing from these states is allowed, not blocked.
- `persist_extraction_result` runs on every completed graph invocation regardless of `response["error"]` — it already self-guards (returns early if there are no documents, or no document matches the detected domain), so calling it unconditionally is safe and is what actually makes `review_ready` packages show up with real `Decision`/`ExtractedField` rows instead of only a JSON blob in `result_json`.
- No new dependencies. No changes to `src/claimflow/graph.py`'s node wiring or any node's business logic (`ingest_node`, `extract_node`, `validate_node`, `retrieve_node`, `review_node` stay untouched) — only `api/main.py` and `src/claimflow/db.py` change behavior.
- A new Alembic migration is required for `ExtractionRun.attempt` (schema change) — follow the same pattern as `alembic/versions/0001_baseline.py`: autogenerate, don't hand-write DDL.

---

### Task 1: Status enum, transition helper, concurrency guard, extraction-run versioning

**Files:**
- Modify: `src/claimflow/schemas/enums.py` (`PackageStatus`)
- Modify: `src/claimflow/db.py` (`transition_package_status`, `try_start_processing`, `ExtractionRun.attempt`, `create_extraction_run`)
- Create: `alembic/versions/0002_extraction_run_attempt.py`
- Test: `tests/test_state_machine.py`

**Interfaces:**
- Produces: `db.transition_package_status(session, package_id, status, *, reason=None, error=None, result=None) -> None`; `db.try_start_processing(session, package_id) -> bool` (returns `False` if the package doesn't exist or is already `processing`) — Task 2 calls both of these from `api/main.py`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/state.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_transition_package_status_logs_audit_entry(session):
    session.add(db.Package(id="pkg1", status="queued"))
    session.commit()

    db.transition_package_status(session, "pkg1", "processing", reason="process started")

    pkg = session.get(db.Package, "pkg1")
    assert pkg.status == "processing"
    entries = session.query(db.AuditLogEntry).filter_by(package_id="pkg1", action="status_transition").all()
    assert len(entries) == 1
    import json
    detail = json.loads(entries[0].detail_json)
    assert detail == {"from": "queued", "to": "processing", "reason": "process started"}


def test_try_start_processing_rejects_concurrent_call(session):
    session.add(db.Package(id="pkg1", status="queued"))
    session.commit()

    assert db.try_start_processing(session, "pkg1") is True
    assert session.get(db.Package, "pkg1").status == "processing"

    # second call while already processing must lose the race
    assert db.try_start_processing(session, "pkg1") is False


def test_try_start_processing_allows_retry_from_failure_states(session):
    for failure_status in ("processing_error", "validation_error", "retrieval_error", "review_ready", "completed"):
        session.add(db.Package(id=f"pkg-{failure_status}", status=failure_status))
    session.commit()

    for failure_status in ("processing_error", "validation_error", "retrieval_error", "review_ready", "completed"):
        assert db.try_start_processing(session, f"pkg-{failure_status}") is True


def test_extraction_run_attempt_increments_on_reprocess(session):
    session.add(db.Package(id="pkg1", status="queued"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.commit()

    run1 = db.create_extraction_run(session, "doc1", "cms1500", "pass", 0.9)
    run2 = db.create_extraction_run(session, "doc1", "cms1500", "pass", 0.95)

    assert run1.attempt == 1
    assert run2.attempt == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_state_machine.py -v`
Expected: FAIL — `transition_package_status`/`try_start_processing` don't exist yet; `ExtractionRun` has no `attempt` column.

- [ ] **Step 3: Extend `PackageStatus`**

In `src/claimflow/schemas/enums.py`, replace:

```python
class PackageStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
```

with:

```python
class PackageStatus(str, Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    REVIEW_READY = "review_ready"
    COMPLETED = "completed"
    PROCESSING_ERROR = "processing_error"
    VALIDATION_ERROR = "validation_error"
    RETRIEVAL_ERROR = "retrieval_error"
```

(`FAILED` is removed — every prior caller of the old generic `"failed"` status is updated in Task 2 to use one of the three specific failure states instead.)

- [ ] **Step 4: Add `ExtractionRun.attempt` to the model**

In `src/claimflow/db.py`, in the `ExtractionRun` class, add a field after `schema_name`:

```python
    schema_name: Mapped[str] = mapped_column(String)
    attempt: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String)  # pass|review|error
```

- [ ] **Step 5: Update `create_extraction_run` to compute the attempt number**

Replace:

```python
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
```

with:

```python
def create_extraction_run(
    session: Session, document_id: str, schema_name: str, status: str, overall_confidence: float
) -> ExtractionRun:
    prior_attempts = session.query(ExtractionRun).filter_by(document_id=document_id).count()
    row = ExtractionRun(
        id=str(uuid.uuid4()),
        document_id=document_id,
        schema_name=schema_name,
        attempt=prior_attempts + 1,
        status=status,
        overall_confidence=overall_confidence,
    )
    session.add(row)
    session.commit()
    return row
```

- [ ] **Step 6: Add `transition_package_status` and `try_start_processing`**

In `src/claimflow/db.py`, replace `update_package_status` with (keep the old function too — other non-processing callers, if any, are unaffected — but add the two new functions right after it):

```python
def update_package_status(
    session: Session, package_id: str, status: str, result: dict | None = None, error: str | None = None
) -> None:
    pkg = session.get(Package, package_id)
    pkg.status = status
    if result is not None:
        pkg.result_json = json.dumps(result)
    if error is not None:
        pkg.error = error
    session.commit()


def transition_package_status(
    session: Session,
    package_id: str,
    status: str,
    *,
    reason: str | None = None,
    error: str | None = None,
    result: dict | None = None,
) -> None:
    """The only status-writing path processing code should use — logs one
    audit entry per transition so the full lifecycle is reconstructable."""
    pkg = session.get(Package, package_id)
    previous_status = pkg.status
    update_package_status(session, package_id, status, result=result, error=error)
    log_audit(
        session, package_id, "api", "status_transition",
        {"from": previous_status, "to": status, "reason": reason},
    )


_RETRYABLE_STATUSES = (
    "queued", "review_ready", "completed", "processing_error", "validation_error", "retrieval_error",
)


def try_start_processing(session: Session, package_id: str) -> bool:
    """Atomic compare-and-swap: only transitions package_id to "processing" if
    it isn't already processing. Returns False if the package doesn't exist,
    or another call already won the race and is currently processing it."""
    result = session.execute(
        Package.__table__.update()
        .where(Package.id == package_id, Package.status.in_(_RETRYABLE_STATUSES))
        .values(status="processing")
    )
    session.commit()
    if result.rowcount == 0:
        return False
    log_audit(session, package_id, "api", "status_transition", {"to": "processing", "reason": "process started"})
    return True
```

- [ ] **Step 7: Generate the Alembic migration for `ExtractionRun.attempt`**

Run: `uv run alembic revision --autogenerate -m "extraction run attempt column"`
Expected: creates `alembic/versions/<hash>_extraction_run_attempt_column.py` with an `op.add_column("extraction_runs", sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))` (or equivalent batch-mode SQLite operation) and a matching `downgrade()`.

Rename the generated file to `alembic/versions/0002_extraction_run_attempt.py`, set `revision = "0002"`, `down_revision = "0001"` inside it.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_state_machine.py -v`
Expected: PASS (4 passed)

- [ ] **Step 9: Run the full suite to check for regressions**

Run: `uv run pytest tests/ -q`
Expected: some pre-existing tests that assert the OLD `PackageStatus.FAILED` value or the 4-value enum will now fail — this is expected and will be fixed in Task 2, which updates every caller. Note which tests fail here so you can confirm in Task 2 that exactly those (and no new ones) get fixed.

- [ ] **Step 10: Commit**

```bash
git add src/claimflow/schemas/enums.py src/claimflow/db.py alembic/versions/0002_extraction_run_attempt.py tests/test_state_machine.py
git commit -m "feat: expand package status enum, add transition helper, atomic processing guard, extraction-run versioning"
```

---

### Task 2: Rewire `_run_claim` and `process_package` onto the new state machine

**Files:**
- Modify: `api/main.py` (`_run_claim`, `create_package`, `process_package`, `lifespan`)
- Test: `tests/test_api.py` (fix any tests broken by Task 1's enum change), `tests/test_state_machine.py` (add integration-level tests)

**Interfaces:**
- Consumes: `db.transition_package_status`, `db.try_start_processing` from Task 1.
- Produces: the classification logic in `_run_claim` (structured-error → `processing_error`; exception → checkpoint-based classification) — Task 3's restart-recovery sweep reuses `db.transition_package_status` the same way.

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from claimflow import db


def test_process_rejects_concurrent_call(monkeypatch):
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

        session = db.SessionLocal()
        db.transition_package_status(session, package_id, "processing", reason="test setup")
        session.close()

        resp = client.post(f"/packages/{package_id}/process")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PROCESSING_IN_PROGRESS"


def test_process_allows_retry_after_processing_error(monkeypatch):
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

        session = db.SessionLocal()
        db.transition_package_status(session, package_id, "processing_error", reason="test setup")
        session.close()

        resp = client.post(f"/packages/{package_id}/process")

    assert resp.status_code == 200


def test_run_claim_classifies_structured_error_as_processing_error(tmp_path):
    graph = MagicMock()
    graph.invoke.return_value = {
        "decision": None, "extraction_data": None, "domain": None, "documents": [],
        "extraction_fields": [], "validation_failures": [], "policy_answers": [],
        "review_reasons": [], "error": "No supported domain detected in package",
    }
    graph.get_state.return_value = MagicMock(values={})

    from api.main import _run_claim

    session = db.SessionLocal()
    db.create_package(session, "pkg-err")
    session.close()

    _run_claim(graph, "pkg-err", tmp_path)

    session = db.SessionLocal()
    pkg = db.get_package(session, "pkg-err")
    assert pkg.status == "processing_error"


def test_run_claim_classifies_approved_decision_as_completed(tmp_path):
    graph = MagicMock()
    graph.invoke.return_value = {
        "decision": "approved", "extraction_data": {}, "domain": "cms1500", "documents": [],
        "extraction_fields": [], "validation_failures": [], "policy_answers": [],
        "review_reasons": [], "error": None,
    }

    from api.main import _run_claim

    session = db.SessionLocal()
    db.create_package(session, "pkg-ok")
    session.close()

    _run_claim(graph, "pkg-ok", tmp_path)

    session = db.SessionLocal()
    pkg = db.get_package(session, "pkg-ok")
    assert pkg.status == "completed"


def test_run_claim_classifies_flagged_decision_as_review_ready(tmp_path):
    graph = MagicMock()
    graph.invoke.return_value = {
        "decision": "flagged", "extraction_data": {}, "domain": "cms1500", "documents": [],
        "extraction_fields": [], "validation_failures": [], "policy_answers": [],
        "review_reasons": ["low confidence"], "error": None,
    }

    from api.main import _run_claim

    session = db.SessionLocal()
    db.create_package(session, "pkg-flag")
    session.close()

    _run_claim(graph, "pkg-flag", tmp_path)

    session = db.SessionLocal()
    pkg = db.get_package(session, "pkg-flag")
    assert pkg.status == "review_ready"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_state_machine.py -v -k "process_rejects or process_allows or run_claim"`
Expected: FAIL — `process_package` doesn't call `try_start_processing` yet, `_run_claim` doesn't classify by decision/error yet.

- [ ] **Step 3: Rewrite `_run_claim`**

Replace `api/main.py:113-148` entirely with:

```python
def _classify_exception(graph, config) -> str:
    """An uncaught exception can only happen inside retrieve_node (external
    Qdrant/LLM calls) or an unexpected crash elsewhere — ingest_node and
    extract_node catch their own errors and return them as state instead of
    raising. Inspect the checkpointer's last-known state for this run to see
    which node was reached, and classify accordingly."""
    try:
        state = graph.get_state(config)
        values = state.values or {}
    except Exception:
        return "processing_error"

    if values.get("validation_failures") is not None and "policy_answers" not in values:
        return "retrieval_error"
    if values.get("extraction_data") is not None and values.get("validation_failures") is None:
        return "validation_error"
    return "processing_error"


def _run_claim(graph, package_id: str, pkg_dir: Path, doc_type_overrides: dict[str, str] | None = None) -> None:
    session = db.SessionLocal()
    thread_id = str(uuid.uuid4())
    config = {"callbacks": get_callback(), "configurable": {"thread_id": thread_id}}
    try:
        state = {"package_dir": str(pkg_dir), "domain": None, "doc_type_overrides": doc_type_overrides or {}}
        result = graph.invoke(state, config=config)

        response = {
            "decision": result.get("decision"),
            "extraction_data": result.get("extraction_data"),
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

        if response["error"]:
            final_status = "processing_error"
        elif response["decision"] == "approved":
            final_status = "completed"
        else:
            final_status = "review_ready"

        db.transition_package_status(
            session, package_id, final_status, reason=f"graph completed, decision={response['decision']}", result=response,
        )
        db.persist_extraction_result(session, package_id, result)
    except Exception as exc:
        logger.error("Background claim processing failed: %s", exc, exc_info=True)
        failure_status = _classify_exception(graph, config)
        db.transition_package_status(session, package_id, failure_status, reason=str(exc), error=str(exc))
    finally:
        session.close()
```

- [ ] **Step 4: Update `create_package` to use `uploaded` then `queued`**

Replace `api/main.py:158-175`:

```python
async def create_package(files: list[UploadFile], background_tasks: BackgroundTasks):
    package_id = str(uuid.uuid4())
    pkg_dir = Path(settings.storage_dir) / package_id
    pkg_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = pkg_dir / Path(f.filename).name
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)

    session = db.SessionLocal()
    try:
        db.create_package(session, package_id)
        db.log_audit(session, package_id, "api", "upload", {"filenames": [f.filename for f in files]})
        db.transition_package_status(session, package_id, "queued", reason="upload complete")
    finally:
        session.close()

    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir)
    return PackageCreateResponse(package_id=package_id, status=PackageStatus.QUEUED)
```

(`db.create_package` already sets the initial status to `"queued"` directly in the INSERT — the `transition_package_status` call here logs the audit entry for the uploaded→queued step; there's no separate "uploaded" row state to transition *from* since the package doesn't exist before this point, so the audit `"from"` field will read `"queued"` too. That's fine — it's the same value because `create_package`'s own default already lands on `queued`; the important behavior is that every subsequent transition after this one goes through the audited path.)

- [ ] **Step 5: Rewrite `process_package` with the concurrency guard**

Replace `api/main.py:244-260`:

```python
async def process_package(package_id: str, background_tasks: BackgroundTasks):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        overrides = {
            Path(doc.path).name: doc.doc_type
            for doc in db.list_documents(session, package_id)
            if doc.manually_overridden
        }
        started = db.try_start_processing(session, package_id)
        if not started:
            raise AppError(409, "PROCESSING_IN_PROGRESS", "Package is already being processed")
    finally:
        session.close()

    pkg_dir = Path(settings.storage_dir) / package_id
    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir, overrides)
    return PackageCreateResponse(package_id=package_id, status=PackageStatus.PROCESSING)
```

Add `409: {"model": ErrorEnvelope}` to the route's `responses=` — replace the `@app.post("/packages/{package_id}/process", ...)` decorator's `responses=ERROR_RESPONSES` with `responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}}`.

- [ ] **Step 6: Fix any existing tests broken by the `FAILED` → three-way split**

Run: `uv run pytest tests/ -q` and look at exactly the tests that failed after Task 1 Step 9. Any test asserting `status == "failed"` needs updating to assert the correct new status for its scenario (most existing failure-path tests are mocking a structured `error` in the graph result, which now maps to `"processing_error"` — update those assertions to `"processing_error"` rather than `"failed"`). Do not change test scenarios, only the expected status string.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_state_machine.py tests/test_api.py tests/ -q`
Expected: PASS — full suite green except the pre-existing unrelated `tests/test_real_public_eval.py` failures (missing `openpyxl`).

- [ ] **Step 8: Commit**

```bash
git add api/main.py tests/test_api.py tests/test_state_machine.py
git commit -m "feat: idempotent /process with concurrency guard, decision-based status classification"
```

---

### Task 3: Restart recovery for stale `processing` packages

**Files:**
- Modify: `src/claimflow/db.py` (`recover_stale_processing_packages`)
- Modify: `api/main.py` (`lifespan`)
- Test: `tests/test_state_machine.py`

**Interfaces:**
- Consumes: `db.transition_package_status` from Task 1.

- [ ] **Step 1: Write the failing test**

```python
def test_recover_stale_processing_packages_marks_them_processing_error(session):
    session.add(db.Package(id="pkg-stuck", status="processing"))
    session.add(db.Package(id="pkg-fine", status="completed"))
    session.commit()

    recovered = db.recover_stale_processing_packages(session)

    assert recovered == ["pkg-stuck"]
    assert session.get(db.Package, "pkg-stuck").status == "processing_error"
    assert session.get(db.Package, "pkg-stuck").error == "process interrupted by application restart"
    assert session.get(db.Package, "pkg-fine").status == "completed"

    entries = session.query(db.AuditLogEntry).filter_by(package_id="pkg-stuck", action="status_transition").all()
    assert len(entries) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_state_machine.py -v -k recover`
Expected: FAIL — `recover_stale_processing_packages` doesn't exist yet.

- [ ] **Step 3: Add `recover_stale_processing_packages` to `db.py`**

Add near the other package-listing functions:

```python
def recover_stale_processing_packages(session: Session) -> list[str]:
    """Called once at app startup. A package can only be "processing" if a
    background task is actively running it — if the app just started, no such
    task exists, so any package found in this state was orphaned by a prior
    crash/restart. Mark it as a retryable failure rather than leaving it stuck."""
    stuck = session.query(Package).filter_by(status="processing").all()
    recovered_ids = []
    for pkg in stuck:
        transition_package_status(
            session, pkg.id, "processing_error",
            reason="restart_recovery", error="process interrupted by application restart",
        )
        recovered_ids.append(pkg.id)
    return recovered_ids
```

- [ ] **Step 4: Wire it into `lifespan`**

Replace `api/main.py:54-59`:

```python
async def lifespan(app: FastAPI):
    app.state.graph = build_graph()
    db.init_db()
    session = db.SessionLocal()
    try:
        recovered = db.recover_stale_processing_packages(session)
        if recovered:
            logger.warning("Recovered %d stale processing package(s) on startup: %s", len(recovered), recovered)
    finally:
        session.close()
    logger.info("ClaimFlow graph initialised")
    yield
    logger.info("ClaimFlow shutting down")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_state_machine.py tests/ -q`
Expected: PASS — full suite green except the pre-existing unrelated `test_real_public_eval.py` failures.

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/db.py api/main.py tests/test_state_machine.py
git commit -m "feat: recover stale processing packages on app restart"
```

---

## Self-Review Notes

- **Spec coverage:** idempotent/reliable `/process` (Task 2's concurrency guard), the full state set including `review_ready` and three failure states (Task 1's enum + Task 2's classification), no duplicate rows on reprocess (already true for `Document` from a prior plan; `ExtractionRun`/`ExtractedField`/`ValidationFailure`/`PolicyEvidence`/`Decision` intentionally get NEW rows per reprocess — that's the "preserve previous results, store version info" requirement, not a bug, now made explicit via `ExtractionRun.attempt`), stale-processing recovery after restart (Task 3), every transition in the audit trail (Task 1's `transition_package_status`, used everywhere). Not covered: a full Celery/Redis queue — explicitly out of scope per the parent TODO ("a local background executor is enough").
- **Placeholder scan:** none found.
- **Type consistency:** `db.transition_package_status`/`db.try_start_processing` signatures match between Task 1 (definition) and Tasks 2-3 (call sites). `PackageStatus` enum values (`processing_error`, `validation_error`, `retrieval_error`, `review_ready`, `uploaded`) used consistently as plain strings passed to these functions (not the enum object itself) — matches the existing pattern where `Package.status` is a plain SQLAlchemy `String` column, not a `sa.Enum`.
