# Dashboard Summary Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /dashboard/summary` so a dashboard UI gets one cheap aggregate call instead of paging through every package to compute counts client-side.

**Architecture:** One new `db.compute_dashboard_summary(session)` function does small `COUNT`/`GROUP BY` queries against `Package`/`Decision`/`ValidationFailure` — no new tables, no denormalized counters to keep in sync. `approved`/`flagged`/`escalated` come from each package's *latest* `Decision` row (the pipeline auto-records one via `persist_extraction_result` on every completed run, and a human reviewer's later `POST /decision` call creates a newer one that wins) rather than from `Package.status` alone, because a package can sit at `status="review_ready"` with either a `flagged` or `escalated` latest decision — status alone can't tell those two apart. `approved` and `status="completed"` are equivalent by construction (the state machine only reaches `completed` when the latest decision is `approved`), so that count is a direct status filter, not a Decision scan.

**Tech Stack:** FastAPI, SQLAlchemy, pytest. No new dependencies, no schema changes, no migration.

## Global Constraints

- Every field in the response is derived from data already persisted (`Package.status`, `Decision.decision`, `ValidationFailure.rule`) — no fabricated or estimated metrics. No "average review time" or similar — no review-start/review-end timestamps exist yet to compute that honestly (matches the parent spec's own instruction to not invent review-time metrics).
- `processing_errors` is one combined count across all three failure statuses (`processing_error`, `validation_error`, `retrieval_error`) — the response has a single field for this, not three.
- `straight_through_rate` = `approved / (approved + flagged + escalated)` — the standard "straight-through processing" definition: fraction of *decided* packages that never needed a human review cycle. `0.0` when there are zero decided packages (avoid division by zero, don't return `null`/`NaN`).
- `top_validation_failures` is the most frequent validation rule names across all CURRENT (non-superseded) `ValidationFailure` rows, each entry `{"rule": str, "count": int}`, sorted by count descending, capped at the top 5.
- No changes to `src/claimflow/graph.py`, any node, or any existing `db.py` function signature — this is purely additive.

---

### Task 1: `db.compute_dashboard_summary` + `GET /dashboard/summary`

**Files:**
- Modify: `src/claimflow/db.py` (`compute_dashboard_summary`)
- Create: `src/claimflow/schemas/dashboard.py` (`DashboardSummaryResponse`, `ValidationFailureCount`)
- Modify: `api/main.py` (new route)
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Produces: `db.compute_dashboard_summary(session) -> dict` with keys `total_packages, processing, awaiting_review, approved, flagged, escalated, processing_errors, straight_through_rate, top_validation_failures` — consumed directly by the new route.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/dashboard.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _pkg_with_decision(session, package_id, status, decision=None, decision_age_days=0):
    from datetime import datetime, timedelta, timezone
    session.add(db.Package(id=package_id, status=status))
    session.commit()
    if decision:
        row = db.create_decision(session, package_id, decision, [])
        row.created_at = datetime.now(timezone.utc) - timedelta(days=decision_age_days)
        session.commit()


def test_dashboard_summary_counts_by_status(session):
    _pkg_with_decision(session, "p1", "processing")
    _pkg_with_decision(session, "p2", "processing")
    _pkg_with_decision(session, "p3", "review_ready", "flagged")
    _pkg_with_decision(session, "p4", "completed", "approved")
    _pkg_with_decision(session, "p5", "processing_error")

    summary = db.compute_dashboard_summary(session)

    assert summary["total_packages"] == 5
    assert summary["processing"] == 2
    assert summary["awaiting_review"] == 1
    assert summary["approved"] == 1
    assert summary["processing_errors"] == 1


def test_dashboard_summary_splits_flagged_vs_escalated_by_latest_decision(session):
    _pkg_with_decision(session, "p1", "review_ready", "flagged")
    _pkg_with_decision(session, "p2", "review_ready", "escalated")
    _pkg_with_decision(session, "p3", "review_ready", "escalated")

    summary = db.compute_dashboard_summary(session)

    assert summary["flagged"] == 1
    assert summary["escalated"] == 2


def test_dashboard_summary_uses_latest_decision_not_first(session):
    session.add(db.Package(id="p1", status="review_ready"))
    session.commit()
    db.create_decision(session, "p1", "escalated", [])
    db.create_decision(session, "p1", "flagged", [])  # reviewer downgraded it later

    summary = db.compute_dashboard_summary(session)

    assert summary["flagged"] == 1
    assert summary["escalated"] == 0


def test_straight_through_rate_computed_from_decided_packages(session):
    _pkg_with_decision(session, "p1", "completed", "approved")
    _pkg_with_decision(session, "p2", "completed", "approved")
    _pkg_with_decision(session, "p3", "review_ready", "flagged")

    summary = db.compute_dashboard_summary(session)

    assert summary["straight_through_rate"] == pytest.approx(2 / 3)


def test_straight_through_rate_zero_when_no_decisions(session):
    _pkg_with_decision(session, "p1", "processing")

    summary = db.compute_dashboard_summary(session)

    assert summary["straight_through_rate"] == 0.0


def test_top_validation_failures_ranked_by_count(session):
    session.add(db.Package(id="p1", status="review_ready"))
    session.add(db.Document(id="d1", package_id="p1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.commit()
    run = db.create_extraction_run(session, "d1", "cms1500", "review", 0.7)
    db.create_validation_failures(session, run.id, [
        {"field": "npi", "rule": "npi_format", "reason": "x"},
        {"field": "npi2", "rule": "npi_format", "reason": "x"},
        {"field": "dob", "rule": "date_range", "reason": "x"},
    ])

    summary = db.compute_dashboard_summary(session)

    assert summary["top_validation_failures"][0] == {"rule": "npi_format", "count": 2}
    assert summary["top_validation_failures"][1] == {"rule": "date_range", "count": 1}


def test_top_validation_failures_excludes_superseded(session):
    session.add(db.Package(id="p1", status="review_ready"))
    session.add(db.Document(id="d1", package_id="p1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.commit()
    run = db.create_extraction_run(session, "d1", "cms1500", "review", 0.7)
    db.create_validation_failures(session, run.id, [{"field": "npi", "rule": "npi_format", "reason": "x"}])
    db.supersede_validation_failures(session, run.id)
    db.create_validation_failures(session, run.id, [{"field": "dob", "rule": "date_range", "reason": "x"}])

    summary = db.compute_dashboard_summary(session)

    rules = {item["rule"] for item in summary["top_validation_failures"]}
    assert "npi_format" not in rules
    assert "date_range" in rules
```

Add to `tests/test_api.py` (matching that file's existing fixture/`TestClient` style):

```python
def test_dashboard_summary_endpoint():
    with TestClient(app) as client:
        resp = client.get("/dashboard/summary")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "total_packages", "processing", "awaiting_review", "approved", "flagged",
        "escalated", "processing_errors", "straight_through_rate", "top_validation_failures",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: FAIL — `db.compute_dashboard_summary` doesn't exist yet.

- [ ] **Step 3: Implement `compute_dashboard_summary`**

Add to `src/claimflow/db.py`, near `list_packages_filtered`:

```python
def compute_dashboard_summary(session: Session) -> dict:
    total_packages = session.query(Package).count()
    processing = session.query(Package).filter(Package.status == "processing").count()
    awaiting_review = session.query(Package).filter(Package.status == "review_ready").count()
    approved = session.query(Package).filter(Package.status == "completed").count()
    processing_errors = (
        session.query(Package)
        .filter(Package.status.in_(("processing_error", "validation_error", "retrieval_error")))
        .count()
    )

    flagged = 0
    escalated = 0
    for pkg in session.query(Package).filter(Package.status == "review_ready").all():
        latest = latest_decision_for_package(session, pkg.id)
        if latest is None:
            continue
        if latest.decision == "flagged":
            flagged += 1
        elif latest.decision == "escalated":
            escalated += 1

    decided_total = approved + flagged + escalated
    straight_through_rate = (approved / decided_total) if decided_total > 0 else 0.0

    rule_counts: dict[str, int] = {}
    for failure in session.query(ValidationFailure).filter_by(superseded=False).all():
        rule_counts[failure.rule] = rule_counts.get(failure.rule, 0) + 1
    top_validation_failures = [
        {"rule": rule, "count": count}
        for rule, count in sorted(rule_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]

    return {
        "total_packages": total_packages,
        "processing": processing,
        "awaiting_review": awaiting_review,
        "approved": approved,
        "flagged": flagged,
        "escalated": escalated,
        "processing_errors": processing_errors,
        "straight_through_rate": straight_through_rate,
        "top_validation_failures": top_validation_failures,
    }
```

- [ ] **Step 4: Add the response schema**

Create `src/claimflow/schemas/dashboard.py`:

```python
from pydantic import BaseModel


class ValidationFailureCount(BaseModel):
    rule: str
    count: int


class DashboardSummaryResponse(BaseModel):
    total_packages: int
    processing: int
    awaiting_review: int
    approved: int
    flagged: int
    escalated: int
    processing_errors: int
    straight_through_rate: float
    top_validation_failures: list[ValidationFailureCount]
```

- [ ] **Step 5: Add the route**

In `api/main.py`, add `from claimflow.schemas.dashboard import DashboardSummaryResponse` to imports, and add near the other top-level routes (after `/health` or alongside the `packages` tag group — use tag `"dashboard"`):

```python
@app.get(
    "/dashboard/summary",
    response_model=DashboardSummaryResponse,
    tags=["dashboard"],
    responses=ERROR_RESPONSES,
)
async def get_dashboard_summary():
    session = db.SessionLocal()
    try:
        return DashboardSummaryResponse(**db.compute_dashboard_summary(session))
    finally:
        session.close()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_dashboard.py tests/test_api.py -v -k dashboard`
Expected: PASS (8 passed)

- [ ] **Step 7: Run the full suite to check for regressions**

Run: `uv run pytest tests/ -q`
Expected: same pass count as baseline plus 8 new tests — purely additive, no existing route touched.

- [ ] **Step 8: Commit**

```bash
git add src/claimflow/db.py src/claimflow/schemas/dashboard.py api/main.py tests/test_dashboard.py tests/test_api.py
git commit -m "feat: add GET /dashboard/summary endpoint"
```

---

## Self-Review Notes

- **Spec coverage:** all 9 fields from the TODO's example response are present with concrete, defensible definitions grounded in stored data — `total_packages`, `processing`, `awaiting_review`, `approved`, `flagged`, `escalated`, `processing_errors` (combined, single field per spec's own field naming), `straight_through_rate` (standard industry definition: approved / all-decided), `top_validation_failures` (current, non-superseded failures only, top 5). No review-time metrics invented (no timestamps for review start/end exist).
- **Placeholder scan:** none found.
- **Type consistency:** `compute_dashboard_summary`'s dict keys match `DashboardSummaryResponse`'s field names exactly (`**db.compute_dashboard_summary(session)` unpacking depends on this) — verified one-to-one correspondence between the two.
