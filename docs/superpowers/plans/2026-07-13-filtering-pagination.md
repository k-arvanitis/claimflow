# Server-Side Filtering + Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /packages` and `GET /reviews/queue` stop returning every row unconditionally — both support `page`, `page_size`, `status`, `domain`, `decision`, `confidence_min`/`confidence_max`, `validation_rule`, `date_from`/`date_to`, `search`, and `sort`, and both return `{"items": [...], "page", "page_size", "total"}`.

**Architecture:** One shared helper, `db.list_packages_filtered(...)`, does the filtering/sorting/pagination for both endpoints — `GET /reviews/queue` is just `GET /packages` with `status` defaulted to `"review_ready"` when the caller doesn't specify one (preserving today's "queue = packages needing review" behavior, now expressed through the state machine's own status instead of a separate flagged/escalated Decision scan). `domain` (the detected schema key, e.g. `"cms1500"`), `decision`, and `confidence` live on `ExtractionRun`/`Decision` rows, not on `Package` itself, so the helper fetches each candidate package's *latest* run/decision (via the existing `latest_extraction_run_for_package`/`latest_decision_for_package` helpers) and filters/sorts on the combined result in Python — a single SQL query narrows by the cheap `Package`-column filters first (`status`, date range, `search`), then the per-package join-equivalent work only touches that narrowed candidate set. This is a `# ponytail:` documented ceiling (fine at the hundreds-of-packages portfolio scale this project targets; would need real SQL joins/window functions if row counts grew to production scale) rather than premature query optimization.

**Tech Stack:** FastAPI (`Query` parameters), SQLAlchemy, pytest. No new dependencies.

## Global Constraints

- Response envelope for both endpoints: `{"items": list[PackageSummary], "page": int, "page_size": int, "total": int}` — `total` is the count of the FULL filtered set, not the page size, so a client can compute total pages.
- `sort` accepts `created_at` or `-created_at` (leading `-` = descending); default `-created_at` (newest first, matches today's behavior on both endpoints).
- `search` matches against `Package.id` (substring, case-insensitive) — there's no other searchable text field on `Package` today (no claimant name column exists anywhere in the schema).
- `GET /reviews/queue` with no `status` query param defaults to `status=review_ready` (today's "flagged" queue, expressed via the Task-3 state machine). Passing an explicit `status` overrides the default — including `status=` (empty string) meaning "no status filter, show everything" is NOT supported; omit the param entirely for that.
- No "assigned reviewer" filter — no reviewer-assignment feature exists in this codebase yet (TODO.md explicitly scopes that filter to "when assignments are added"); do not add a stub column or filter for it.
- `page`/`page_size` are 1-indexed; `page_size` capped at 100 (reject or clamp — clamp, don't 422, to match this project's existing lenient-query-param style).
- No changes to `src/claimflow/graph.py`, any node, or `db.py`'s existing single-package helpers (`latest_extraction_run_for_package`, `latest_decision_for_package`) — this plan calls them, doesn't change them.

---

### Task 1: Shared filtering/pagination helper

**Files:**
- Modify: `src/claimflow/db.py` (`list_packages_filtered`)
- Test: `tests/test_pagination.py`

**Interfaces:**
- Produces: `db.list_packages_filtered(session, *, status=None, domain=None, decision=None, confidence_min=None, confidence_max=None, validation_rule=None, date_from=None, date_to=None, search=None, sort="-created_at", page=1, page_size=25) -> tuple[list[Package], int]` — Task 2 wires this directly into both routes.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/pagination.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(session, package_id, status, domain=None, decision=None, confidence=None, rule=None, days_ago=0):
    session.add(db.Package(
        id=package_id, status=status,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    ))
    session.commit()
    if domain or confidence is not None:
        session.add(db.Document(id=f"{package_id}-doc", package_id=package_id, path=f"{package_id}.pdf", doc_type=domain or "cms1500", has_text_layer=True))
        session.commit()
        run = db.create_extraction_run(session, f"{package_id}-doc", domain or "cms1500", "review", confidence or 0.8)
        if rule:
            db.create_validation_failures(session, run.id, [{"field": "x", "rule": rule, "reason": "r"}])
    if decision:
        db.create_decision(session, package_id, decision, [])


def test_pagination_returns_correct_page_and_total(session):
    for i in range(5):
        _seed(session, f"pkg{i}", "completed", days_ago=i)

    rows, total = db.list_packages_filtered(session, page=1, page_size=2)
    assert total == 5
    assert len(rows) == 2
    assert rows[0].id == "pkg0"  # newest first, default sort


def test_filter_by_status(session):
    _seed(session, "pkg-a", "completed")
    _seed(session, "pkg-b", "review_ready")

    rows, total = db.list_packages_filtered(session, status="review_ready")
    assert total == 1
    assert rows[0].id == "pkg-b"


def test_filter_by_domain(session):
    _seed(session, "pkg-a", "completed", domain="cms1500")
    _seed(session, "pkg-b", "completed", domain="xactimate")

    rows, total = db.list_packages_filtered(session, domain="xactimate")
    assert total == 1
    assert rows[0].id == "pkg-b"


def test_filter_by_decision(session):
    _seed(session, "pkg-a", "completed", decision="approved")
    _seed(session, "pkg-b", "review_ready", decision="escalated")

    rows, total = db.list_packages_filtered(session, decision="escalated")
    assert total == 1
    assert rows[0].id == "pkg-b"


def test_filter_by_confidence_range(session):
    _seed(session, "pkg-a", "completed", domain="cms1500", confidence=0.95)
    _seed(session, "pkg-b", "review_ready", domain="cms1500", confidence=0.4)

    rows, total = db.list_packages_filtered(session, confidence_max=0.5)
    assert total == 1
    assert rows[0].id == "pkg-b"


def test_filter_by_validation_rule(session):
    _seed(session, "pkg-a", "completed", domain="cms1500", confidence=0.9, rule="npi_format")
    _seed(session, "pkg-b", "completed", domain="cms1500", confidence=0.9, rule="date_range")

    rows, total = db.list_packages_filtered(session, validation_rule="npi_format")
    assert total == 1
    assert rows[0].id == "pkg-a"


def test_filter_by_date_range(session):
    _seed(session, "pkg-old", "completed", days_ago=10)
    _seed(session, "pkg-new", "completed", days_ago=0)

    rows, total = db.list_packages_filtered(session, date_from=datetime.now(timezone.utc) - timedelta(days=1))
    assert total == 1
    assert rows[0].id == "pkg-new"


def test_search_matches_package_id_substring(session):
    _seed(session, "abc123", "completed")
    _seed(session, "xyz789", "completed")

    rows, total = db.list_packages_filtered(session, search="abc")
    assert total == 1
    assert rows[0].id == "abc123"


def test_sort_ascending(session):
    _seed(session, "pkg-a", "completed", days_ago=5)
    _seed(session, "pkg-b", "completed", days_ago=1)

    rows, _ = db.list_packages_filtered(session, sort="created_at")
    assert rows[0].id == "pkg-a"  # oldest first


def test_page_size_clamped_to_max(session):
    for i in range(3):
        _seed(session, f"pkg{i}", "completed")

    rows, total = db.list_packages_filtered(session, page_size=99999)
    assert len(rows) == 3  # clamped, not rejected, just bounded by actual data here
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pagination.py -v`
Expected: FAIL — `list_packages_filtered` doesn't exist yet.

- [ ] **Step 3: Implement `list_packages_filtered`**

Add to `src/claimflow/db.py`, near `list_packages`:

```python
MAX_PAGE_SIZE = 100


def list_packages_filtered(
    session: Session,
    *,
    status: str | None = None,
    domain: str | None = None,
    decision: str | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    validation_rule: str | None = None,
    date_from: "datetime | None" = None,
    date_to: "datetime | None" = None,
    search: str | None = None,
    sort: str = "-created_at",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list["Package"], int]:
    """Filters/sorts/paginates packages. Cheap column filters (status, date range,
    search) run in SQL first; domain/decision/confidence/validation_rule — which
    live on each package's LATEST ExtractionRun/Decision, not on Package itself —
    are applied in Python over that narrowed candidate set.

    ponytail: this fetches the full narrowed candidate set into Python before the
    run/decision-level filters and pagination slice. Fine at portfolio scale
    (hundreds of packages); would need real SQL joins/window functions if package
    counts grew to production scale.
    """
    query = session.query(Package)
    if status is not None:
        query = query.filter(Package.status == status)
    if date_from is not None:
        query = query.filter(Package.created_at >= date_from)
    if date_to is not None:
        query = query.filter(Package.created_at <= date_to)
    if search:
        query = query.filter(Package.id.ilike(f"%{search}%"))

    candidates = query.all()

    def _matches(pkg: Package) -> bool:
        if domain is not None or confidence_min is not None or confidence_max is not None or validation_rule is not None:
            run = latest_extraction_run_for_package(session, pkg.id)
            if run is None:
                return False
            if domain is not None and run.schema_name != domain:
                return False
            if confidence_min is not None and run.overall_confidence < confidence_min:
                return False
            if confidence_max is not None and run.overall_confidence > confidence_max:
                return False
            if validation_rule is not None:
                failures = list_validation_failures_for_run(session, run.id, current_only=True)
                if not any(f.rule == validation_rule for f in failures):
                    return False
        if decision is not None:
            latest = latest_decision_for_package(session, pkg.id)
            if latest is None or latest.decision != decision:
                return False
        return True

    filtered = [pkg for pkg in candidates if _matches(pkg)]

    descending = sort.startswith("-")
    filtered.sort(key=lambda p: p.created_at, reverse=descending)

    total = len(filtered)
    page = max(page, 1)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    start = (page - 1) * page_size
    return filtered[start : start + page_size], total
```

Add `from datetime import datetime` to the type hint if not already imported at module level (it already is, per the existing `datetime.now(timezone.utc)` defaults elsewhere in this file) — remove the string-quoted forward-ref annotations (`"datetime | None"`, `"Package"`) and use the real types directly since `datetime` and `Package` are already in scope in this module.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pagination.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest tests/ -q`
Expected: same pass count as baseline plus 10 — this task only adds a new function, doesn't change any existing call site yet.

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/db.py tests/test_pagination.py
git commit -m "feat: add filtering/sorting/pagination helper for package listings"
```

---

### Task 2: Wire `GET /packages` and `GET /reviews/queue` onto the shared helper

**Files:**
- Create: `src/claimflow/schemas/pagination.py` (`PaginatedPackagesResponse`)
- Modify: `api/main.py` (`list_packages`, `reviews_queue`)
- Test: `tests/test_pagination.py`, `tests/test_api.py` (fix any tests asserting the old bare-list response shape)

**Interfaces:**
- Consumes: `db.list_packages_filtered` from Task 1.

- [ ] **Step 1: Write the failing test**

```python
def test_list_packages_endpoint_paginates(monkeypatch):
    with TestClient(app) as client:
        for _ in range(3):
            create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        resp = client.get("/packages?page=1&page_size=2")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "page", "page_size", "total"}
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] >= 3
    assert len(body["items"]) == 2


def test_reviews_queue_defaults_to_review_ready_status(monkeypatch):
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

        session = db.SessionLocal()
        db.transition_package_status(session, package_id, "review_ready", reason="test setup")
        session.close()

        resp = client.get("/reviews/queue")

    body = resp.json()
    assert any(item["package_id"] == package_id for item in body["items"])


def test_reviews_queue_explicit_status_overrides_default(monkeypatch):
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]
        resp = client.get("/reviews/queue?status=queued")

    body = resp.json()
    assert any(item["package_id"] == package_id for item in body["items"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pagination.py -v -k "endpoint or queue"`
Expected: FAIL — routes don't accept query params or return the envelope shape yet.

- [ ] **Step 3: Add `PaginatedPackagesResponse`**

Create `src/claimflow/schemas/pagination.py`:

```python
from pydantic import BaseModel

from claimflow.schemas.packages import PackageSummary


class PaginatedPackagesResponse(BaseModel):
    items: list[PackageSummary]
    page: int
    page_size: int
    total: int
```

- [ ] **Step 4: Rewrite `list_packages` and `reviews_queue`**

In `api/main.py`, add `from fastapi import Query` to imports if not already present (check — `Query` may not be imported yet since no route uses it today), and `from datetime import datetime`, and `from claimflow.schemas.pagination import PaginatedPackagesResponse`.

Replace `api/main.py:226-240` (verify exact current line range first):

```python
@app.get(
    "/packages",
    response_model=PaginatedPackagesResponse,
    tags=["packages"],
    responses=ERROR_RESPONSES,
)
async def list_packages(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1),
    status: str | None = None,
    domain: str | None = None,
    decision: str | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    validation_rule: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    sort: str = "-created_at",
):
    session = db.SessionLocal()
    try:
        rows, total = db.list_packages_filtered(
            session, status=status, domain=domain, decision=decision,
            confidence_min=confidence_min, confidence_max=confidence_max,
            validation_rule=validation_rule, date_from=date_from, date_to=date_to,
            search=search, sort=sort, page=page, page_size=page_size,
        )
        return PaginatedPackagesResponse(
            items=[PackageSummary(package_id=pkg.id, status=pkg.status, created_at=pkg.created_at) for pkg in rows],
            page=page, page_size=min(page_size, db.MAX_PAGE_SIZE), total=total,
        )
    finally:
        session.close()
```

Replace `api/main.py:474-487` (verify exact current line range first):

```python
@app.get(
    "/reviews/queue",
    response_model=PaginatedPackagesResponse,
    tags=["review"],
    responses=ERROR_RESPONSES,
)
async def reviews_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1),
    status: str | None = None,
    domain: str | None = None,
    decision: str | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    validation_rule: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    sort: str = "-created_at",
):
    session = db.SessionLocal()
    try:
        rows, total = db.list_packages_filtered(
            session, status=status or "review_ready", domain=domain, decision=decision,
            confidence_min=confidence_min, confidence_max=confidence_max,
            validation_rule=validation_rule, date_from=date_from, date_to=date_to,
            search=search, sort=sort, page=page, page_size=page_size,
        )
        return PaginatedPackagesResponse(
            items=[PackageSummary(package_id=pkg.id, status=pkg.status, created_at=pkg.created_at) for pkg in rows],
            page=page, page_size=min(page_size, db.MAX_PAGE_SIZE), total=total,
        )
    finally:
        session.close()
```

- [ ] **Step 5: Fix any pre-existing tests asserting the old bare-list response shape**

Run: `uv run pytest tests/ -q` and find every test that does `resp.json() == [...]` or indexes the response as a bare list for `/packages` or `/reviews/queue`. Update each to read `resp.json()["items"]` instead. Do not change what scenario each test verifies — only the shape it reads the result through.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_pagination.py tests/test_api.py tests/ -q`
Expected: PASS — full suite green except the 3 pre-existing unrelated `tests/test_real_public_eval.py` failures.

- [ ] **Step 7: Commit**

```bash
git add src/claimflow/schemas/pagination.py api/main.py tests/test_pagination.py tests/test_api.py
git commit -m "feat: paginate and filter GET /packages and GET /reviews/queue"
```

---

## Self-Review Notes

- **Spec coverage:** `page`/`page_size`/`status`/`domain`/`decision`/`sort`/`search` on `GET /packages` (Task 2); `GET /reviews/queue` gets the same set plus confidence range, validation rule, date range (Task 1's helper covers all of these, Task 2 wires them into both routes with `reviews_queue`'s `status` default preserving today's flagged-queue behavior). `{"items","page","page_size","total"}` envelope on both. Assigned-reviewer filter explicitly excluded (no such feature exists yet, matches TODO's own conditional scoping).
- **Placeholder scan:** none found.
- **Type consistency:** `db.list_packages_filtered`'s keyword arguments match exactly between Task 1 (definition) and Task 2 (call sites in both routes) — same names, same defaults where applicable (`sort="-created_at"` in both).
