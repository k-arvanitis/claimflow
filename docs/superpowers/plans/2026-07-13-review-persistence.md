# Review Persistence Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the backend actually keeps machine value, reviewer correction, and reviewer context distinct (it mostly already does — `ReviewAction` never touches `ExtractedField.value_json`), then close the two real gaps: `POST /packages/{id}/validation/re-run` currently persists nothing at all (returns failures, writes zero rows), and `POST /packages/{id}/fields/{id}/review` inserts a fresh `ReviewAction` row on every call with no dedup, so an accidental double-submit creates two identical audit entries.

**Architecture:** No new tables, no `ExtractionRun`-per-rerun scheme — that would force every read path (`get_package_review`, the evidence endpoint, `/reviews/queue`) to reconcile which run is "current," which is far more machinery than this task needs. Instead: `ValidationFailure` gains one `superseded: bool` column; a rerun marks the current run's existing failures superseded (an `UPDATE`, never a `DELETE` — audit trail intact) and inserts the new set as current. `get_package_review` is updated to show only current (non-superseded) failures; a new `list_validation_failures_for_run(session, run_id, current_only=True)` parameter serves both views. Decision-change detection reuses `review_node` as a pure function (state-in, decision-out) instead of reimplementing threshold logic — it already has no side effects beyond reading `settings`. `submit_field_review` gains a dedup check: if the most recent `ReviewAction` for `(extraction_run_id, field_name)` already has the identical `(action, corrected_value, reviewer, note)`, return it instead of inserting a duplicate.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic (migration for the new column), pytest.

## Global Constraints

- `ExtractedField.value_json` (the machine value) is never written by review code — verify this with a test, don't add a parallel "final value" column; the final approved value for a field is derivable as `latest ReviewAction.corrected_value_json` if one exists, else `ExtractedField.value_json` unchanged. No new column for this.
- `ValidationFailure` rows are never deleted by a rerun — only marked `superseded=True` before the new batch is inserted. `list_validation_failures_for_run` keeps returning everything (the audit view); a new optional `current_only=True` parameter filters to the live set.
- Decision-change detection calls `claimflow.nodes.review.review_node` directly with a synthetic partial state (`{"error": None, "extraction_overall_confidence": ..., "validation_failures": ...}`) — do not reimplement the confidence/threshold logic that already lives there.
- `POST /packages/{id}/validation/re-run` does NOT auto-persist a new `Decision` row — it only reports whether the decision *would* change; recording the actual final decision stays the reviewer's separate, deliberate `POST /packages/{id}/decision` call.
- No changes to `src/claimflow/nodes/review.py` itself (only called, not modified) or to the LangGraph pipeline.
- New Alembic migration required for `ValidationFailure.superseded` — autogenerate, chain `down_revision` to `"0002"`.

---

### Task 1: Verify machine/correction separation, add field-review dedup

**Files:**
- Modify: `src/claimflow/db.py` (`record_review_action`)
- Test: `tests/test_review_persistence.py`

**Interfaces:**
- Produces: `record_review_action`'s dedup behavior — Task 2/3 don't depend on this directly, but the test file they extend lives in the same module.

- [ ] **Step 1: Write the failing test**

```python
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/review.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_field(session, value=("DOE JOHN",)):
    session.add(db.Package(id="pkg1", status="review_ready"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.add(db.ExtractionRun(id="run1", document_id="doc1", schema_name="cms1500", status="review", overall_confidence=0.8))
    field = db.ExtractedField(
        extraction_run_id="run1", name="patient_name", value_json=json.dumps(value[0]),
        confidence=0.8, grounded=True, valid=True, field_status="review",
    )
    session.add(field)
    session.commit()
    return field


def test_review_action_never_overwrites_machine_value(session):
    field = _seed_field(session)
    original_value_json = field.value_json

    db.record_review_action(
        session, "run1", "patient_name", "edit",
        original_value="DOE JOHN", corrected_value="DOE JON",
        reviewer="alice",
    )

    refreshed = session.get(db.ExtractedField, field.id)
    assert refreshed.value_json == original_value_json


def test_repeated_identical_review_action_does_not_duplicate(session):
    _seed_field(session)

    first = db.record_review_action(
        session, "run1", "patient_name", "edit",
        original_value="DOE JOHN", corrected_value="DOE JON", reviewer="alice", note="typo fix",
    )
    second = db.record_review_action(
        session, "run1", "patient_name", "edit",
        original_value="DOE JOHN", corrected_value="DOE JON", reviewer="alice", note="typo fix",
    )

    assert first.id == second.id
    assert session.query(db.ReviewAction).filter_by(extraction_run_id="run1", field_name="patient_name").count() == 1


def test_distinct_review_action_creates_new_row(session):
    _seed_field(session)

    first = db.record_review_action(
        session, "run1", "patient_name", "edit", corrected_value="DOE JON", reviewer="alice",
    )
    second = db.record_review_action(
        session, "run1", "patient_name", "edit", corrected_value="DOE JONATHAN", reviewer="alice",
    )

    assert first.id != second.id
    assert session.query(db.ReviewAction).filter_by(extraction_run_id="run1", field_name="patient_name").count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review_persistence.py -v`
Expected: `test_review_action_never_overwrites_machine_value` PASSES already (nothing to fix there — confirms the constraint). `test_repeated_identical_review_action_does_not_duplicate` FAILS (two rows currently created). `test_distinct_review_action_creates_new_row` PASSES already.

- [ ] **Step 3: Add the dedup check to `record_review_action`**

Replace `src/claimflow/db.py:378-404`:

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
    corrected_value_json = json.dumps(corrected_value) if corrected_value is not None else None
    existing = (
        session.query(ReviewAction)
        .filter_by(extraction_run_id=extraction_run_id, field_name=field_name)
        .order_by(ReviewAction.created_at.desc())
        .first()
    )
    if (
        existing is not None
        and existing.action == action
        and existing.corrected_value_json == corrected_value_json
        and existing.reviewer == reviewer
        and existing.note == note
    ):
        return existing

    row = ReviewAction(
        extraction_run_id=extraction_run_id,
        field_name=field_name,
        action=action,
        original_value_json=json.dumps(original_value) if original_value is not None else None,
        corrected_value_json=corrected_value_json,
        validation_before_json=json.dumps(validation_before) if validation_before is not None else None,
        validation_after_json=json.dumps(validation_after) if validation_after is not None else None,
        reviewer=reviewer,
        note=note,
    )
    session.add(row)
    session.commit()
    return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_persistence.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest tests/ -q`
Expected: same pass count as baseline plus 3 — no existing test relies on `record_review_action` always inserting a fresh row (verify this is actually true rather than assuming).

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/db.py tests/test_review_persistence.py
git commit -m "feat: dedupe identical repeated field-review submissions"
```

---

### Task 2: Persist validation-rerun results without destroying prior failures

**Files:**
- Modify: `src/claimflow/db.py` (`ValidationFailure` model, `list_validation_failures_for_run`, new `supersede_validation_failures`, `create_validation_failures`)
- Create: `alembic/versions/0003_validation_failure_superseded.py`
- Modify: `api/main.py` (`get_package_review`, `rerun_package_validation`)
- Modify: `src/claimflow/schemas/review_write.py` (`ValidationRerunResponse`)
- Test: `tests/test_review_persistence.py`

**Interfaces:**
- Produces: `db.list_validation_failures_for_run(session, extraction_run_id, current_only=False)`, `db.supersede_validation_failures(session, extraction_run_id) -> None` — Task 3 calls the same rerun code path, no new interface needed there.

- [ ] **Step 1: Write the failing test**

```python
def test_rerun_persists_new_failures_and_supersedes_old(session):
    _seed_field(session)
    session.add(db.ValidationFailure(extraction_run_id="run1", field="patient_dob", rule="mandatory", reason="missing"))
    session.commit()

    db.supersede_validation_failures(session, "run1")
    db.create_validation_failures(session, "run1", [{"field": "patient_name", "rule": "mandatory", "reason": "still wrong"}])

    all_failures = db.list_validation_failures_for_run(session, "run1")
    current = db.list_validation_failures_for_run(session, "run1", current_only=True)

    assert len(all_failures) == 2  # old one retained, not deleted
    assert len(current) == 1
    assert current[0].field == "patient_name"
    assert all(f.superseded for f in all_failures if f.field == "patient_dob")
```

Add to `tests/test_api.py` (or `tests/test_review_persistence.py` if it more naturally fits there — use your judgment on which existing test file already has a `TestClient` + package fixture pattern to reuse):

```python
def test_rerun_validation_endpoint_persists_results(monkeypatch):
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

        session = db.SessionLocal()
        db.update_package_status(session, package_id, "review_ready", result={
            "domain": "cms1500", "extraction_data": {"patient_name": "DOE JOHN"},
        })
        session.close()

        resp = client.post(f"/packages/{package_id}/validation/re-run", json={"corrected_fields": {"patient_name": "DOE JON"}})

    assert resp.status_code == 200
    body = resp.json()
    assert "decision" in body
    assert "decision_changed" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review_persistence.py tests/test_api.py -v -k "rerun"`
Expected: FAIL — `ValidationFailure.superseded` doesn't exist, `supersede_validation_failures` doesn't exist, the endpoint doesn't return `decision`/`decision_changed` yet.

- [ ] **Step 3: Add `superseded` to the `ValidationFailure` model**

In `src/claimflow/db.py`, replace the `ValidationFailure` class (`db.py:121-131`):

```python
class ValidationFailure(Base):
    __tablename__ = "validation_failures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String)
    rule: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    superseded: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    extraction_run: Mapped["ExtractionRun"] = relationship(back_populates="validation_failures")
```

- [ ] **Step 4: Add `supersede_validation_failures` and update `list_validation_failures_for_run`**

Replace `src/claimflow/db.py:473-474`:

```python
def list_validation_failures_for_run(session: Session, extraction_run_id: str) -> list[ValidationFailure]:
    return list(session.query(ValidationFailure).filter_by(extraction_run_id=extraction_run_id).all())
```

with:

```python
def list_validation_failures_for_run(
    session: Session, extraction_run_id: str, current_only: bool = False
) -> list[ValidationFailure]:
    query = session.query(ValidationFailure).filter_by(extraction_run_id=extraction_run_id)
    if current_only:
        query = query.filter_by(superseded=False)
    return list(query.all())


def supersede_validation_failures(session: Session, extraction_run_id: str) -> None:
    """Marks a run's current validation failures as historical (audit trail) —
    never deletes them — so a rerun's new failures become the only "current" set."""
    session.query(ValidationFailure).filter_by(extraction_run_id=extraction_run_id, superseded=False).update(
        {"superseded": True}
    )
    session.commit()
```

- [ ] **Step 5: Generate the Alembic migration**

Run: `uv run alembic revision --autogenerate -m "validation failure superseded column"`
Rename to `alembic/versions/0003_validation_failure_superseded.py`, set `revision = "0003"`, `down_revision = "0002"`.

- [ ] **Step 6: Update `get_package_review` to show only current failures**

In `api/main.py`, change the `get_package_review` route's failures query:

```python
        failures = db.list_validation_failures_for_run(session, run.id, current_only=True) if run else []
```

(single-line change to the existing `failures = db.list_validation_failures_for_run(session, run.id) if run else []` call)

- [ ] **Step 7: Extend `ValidationRerunResponse` and wire persistence into the route**

In `src/claimflow/schemas/review_write.py`, add to `ValidationRerunResponse`:

```python
class ValidationRerunResponse(BaseModel):
    validation_failures: list[ValidationFailureItem]
    decision: DecisionType
    decision_changed: bool
    previous_decision: DecisionType | None
```

(add `from claimflow.schemas.enums import DecisionType` to that file's imports if not already present — check first, `DecisionRequest`/`DecisionResponse` in the same file already import it)

Replace `api/main.py`'s `rerun_package_validation` (currently at `api/main.py:549-565`, verify exact line number before editing):

```python
@app.post(
    "/packages/{package_id}/validation/re-run",
    response_model=ValidationRerunResponse,
    tags=["review"],
    responses=ERROR_RESPONSES,
)
async def rerun_package_validation(package_id: str, body: ValidationRerunRequest):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        result = json.loads(pkg.result_json) if pkg.result_json else {}
        run = db.latest_extraction_run_for_package(session, package_id)
        previous_decision_row = db.latest_decision_for_package(session, package_id)
        previous_decision = previous_decision_row.decision if previous_decision_row else None

        domain = result.get("domain")
        merged = dict(result.get("extraction_data") or {})
        merged.update(body.corrected_fields)
        failures = review.rerun_validation(domain, merged)

        if run is not None:
            db.supersede_validation_failures(session, run.id)
            db.create_validation_failures(
                session, run.id, [{"field": f["field"], "rule": f["rule"], "reason": f["reason"]} for f in failures]
            )

        review_state = {
            "error": None,
            "extraction_overall_confidence": run.overall_confidence if run else 0.0,
            "validation_failures": failures,
        }
        outcome = review_node(review_state)
        new_decision = outcome["decision"]

        db.log_audit(
            session, package_id, "api", "validation_rerun",
            {"validation_failures": [dict(f) for f in failures], "decision": new_decision, "previous_decision": previous_decision},
        )
    finally:
        session.close()

    return ValidationRerunResponse(
        validation_failures=[ValidationFailureItem(field=f["field"], rule=f["rule"], reason=f["reason"]) for f in failures],
        decision=new_decision,
        decision_changed=new_decision != previous_decision,
        previous_decision=previous_decision,
    )
```

Add `from claimflow.nodes.review import review_node` to `api/main.py`'s imports.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_persistence.py tests/test_api.py tests/ -q`
Expected: PASS — full suite green.

- [ ] **Step 9: Commit**

```bash
git add src/claimflow/db.py alembic/versions/0003_validation_failure_superseded.py api/main.py src/claimflow/schemas/review_write.py tests/test_review_persistence.py tests/test_api.py
git commit -m "feat: persist validation-rerun results, retain prior failures for audit, report decision change"
```

---

## Self-Review Notes

- **Spec coverage:** machine value never overwritten by review (verified, not rebuilt), original/corrected/reviewer/note/timestamp all already queryable via `ReviewAction` joined to `ExtractionRun.attempt` for version (no new columns needed there), no duplicate review actions on repeat (Task 1), validation rerun persists + retains history + reports decision change (Task 2). Not covered: row-level identity for nested/list fields (explicitly TODO item #5, a separate plan) — this plan only touches scalar-field review and validation rerun.
- **Placeholder scan:** none found.
- **Type consistency:** `list_validation_failures_for_run`'s new `current_only` parameter is additive (default `False` preserves existing callers' behavior) — checked every existing call site (`get_package_review`, the new test) to confirm none breaks.
