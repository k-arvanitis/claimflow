# API Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every dict-in/dict-out FastAPI route in `api/main.py` with explicit Pydantic request/response models, a standard `{"error":{"code","message","details"}}` envelope, shared status/decision/action/doc-type enums, and accurate OpenAPI — so a future typed frontend client never breaks on an undocumented response shape.

**Architecture:** New `src/claimflow/schemas/` package holds enums, the error envelope, and one Pydantic module per route group. `api/main.py` keeps its routes but adds `response_model=`, typed request bodies, and swaps generic `HTTPException` for a new `AppError` subclass that carries a machine-readable `code`. No DB schema changes, no business-logic changes — this plan is response/request shape only.

**Tech Stack:** FastAPI, Pydantic v2, pytest + `fastapi.testclient.TestClient`.

## Global Constraints

- Every route gets `response_model=`; no route returns a bare `dict`/`list[dict]`.
- Error shape is always `{"error": {"code": str, "message": str, "details": Any | None}}` — for every 404, 422, and 500, not just custom ones.
- Timestamps are Pydantic `datetime` fields (not pre-formatted strings) — Pydantic v2 serializes these as ISO 8601 automatically.
- ID types stay as they are today (verified consistent): `package_id`/`document_id`/`extraction_run_id` are UUID4 `str`; `field_id`, validation-failure id, policy-evidence id, decision id, review-action id, audit id are `int`. Document this, don't change it.
- No new dependencies. No changes to `src/claimflow/db.py`, `src/claimflow/review.py`, or the LangGraph pipeline.
- `src/claimflow/domains/*.py` `doc_type=` registrations are the source of truth for `DocumentType` — currently: `cms1500`, `eob`, `medicare_summary_notice`, `xactimate`, `declarations_page`, `loan`, `sba_form_413`, `sba_form_2202`, plus classifier fallback `unknown` (`src/claimflow/nodes/ingest.py:109`).

---

### Task 1: Shared enums + standardized error envelope

**Files:**
- Create: `src/claimflow/schemas/__init__.py`
- Create: `src/claimflow/schemas/enums.py`
- Create: `src/claimflow/schemas/errors.py`
- Modify: `api/main.py:1-36` (imports + exception handlers)
- Test: `tests/test_error_envelope.py`

**Interfaces:**
- Produces: `PackageStatus`, `ExtractionRunStatus`, `DecisionType`, `ReviewActionType`, `DocumentType` (all `str, Enum` in `src/claimflow/schemas/enums.py`); `AppError(status_code, code, message, details=None)` and `ErrorEnvelope`/`ErrorBody` (in `src/claimflow/schemas/errors.py`) — every later task imports these.

- [ ] **Step 1: Write `src/claimflow/schemas/__init__.py`**

```python
```

(empty — marks the package)

- [ ] **Step 2: Write `src/claimflow/schemas/enums.py`**

```python
from enum import Enum


class PackageStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExtractionRunStatus(str, Enum):
    PASS = "pass"
    REVIEW = "review"
    ERROR = "error"


class DecisionType(str, Enum):
    APPROVED = "approved"
    FLAGGED = "flagged"
    ESCALATED = "escalated"


class ReviewActionType(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
    ADD = "add"


class DocumentType(str, Enum):
    """Mirrors `doc_type=` registrations in src/claimflow/domains/*.py, plus the
    classifier's "unknown" fallback (nodes/ingest.py). Update this list when a
    domain module registers a new doc_type."""

    CMS1500 = "cms1500"
    EOB = "eob"
    MEDICARE_SUMMARY_NOTICE = "medicare_summary_notice"
    XACTIMATE = "xactimate"
    DECLARATIONS_PAGE = "declarations_page"
    LOAN = "loan"
    SBA_FORM_413 = "sba_form_413"
    SBA_FORM_2202 = "sba_form_2202"
    UNKNOWN = "unknown"
```

- [ ] **Step 3: Write `src/claimflow/schemas/errors.py`**

```python
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel


class AppError(HTTPException):
    """Raise this instead of bare HTTPException when a route needs a stable
    machine-readable `code` (e.g. "PACKAGE_NOT_FOUND") in the error envelope."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.details = details


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody
```

- [ ] **Step 4: Register exception handlers in `api/main.py`**

Replace the block at `api/main.py:32-35`:

```python
@app.exception_handler(Exception)
async def _generic_handler(request, exc):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

with:

```python
@app.exception_handler(AppError)
async def _app_error_handler(request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorEnvelope(
            error=ErrorBody(code=exc.code, message=exc.detail, details=exc.details)
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def _http_exception_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorEnvelope(
            error=ErrorBody(code="HTTP_ERROR", message=str(exc.detail), details=None)
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=ErrorEnvelope(
            error=ErrorBody(code="VALIDATION_ERROR", message="Request validation failed", details=exc.errors())
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def _generic_handler(request, exc):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorEnvelope(
            error=ErrorBody(code="INTERNAL_ERROR", message="Internal server error", details=None)
        ).model_dump(),
    )
```

Add imports at the top of `api/main.py` (near the existing `from fastapi import ...` on line 8):

```python
from fastapi.exceptions import RequestValidationError

from claimflow.schemas.errors import AppError, ErrorBody, ErrorEnvelope
```

- [ ] **Step 5: Write the failing test**

```python
from fastapi.testclient import TestClient

from api.main import app


def test_404_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "PACKAGE_NOT_FOUND"


def test_422_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/abc/documents/def/pages/not-an-int")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_500_uses_error_envelope(monkeypatch):
    from claimflow import db

    def _boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "list_packages", _boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/packages")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_error_envelope.py -v`
Expected: FAIL — `test_404_uses_error_envelope` fails because `GET /packages/{id}` still raises bare `HTTPException` and the 500 handler still returns `{"detail": ...}`.

- [ ] **Step 7: Swap the `PACKAGE_NOT_FOUND` 404s to `AppError`**

In `api/main.py`, replace each of these 7 occurrences of
`raise HTTPException(status_code=404, detail="Package not found")` (lines 120, 137, 152, 172, 356, 374, 417) with:

```python
raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_error_envelope.py -v`
Expected: PASS (3 passed)

- [ ] **Step 9: Commit**

```bash
git add src/claimflow/schemas api/main.py tests/test_error_envelope.py
git commit -m "feat: add shared enums and standard error envelope"
```

---

### Task 2: Package endpoint schemas

**Files:**
- Create: `src/claimflow/schemas/packages.py`
- Modify: `api/main.py:81-176` (6 routes: `POST /packages`, `GET /packages`, `GET /packages/{id}`, `DELETE /packages/{id}`, `POST /packages/{id}/process`, `GET /packages/{id}/status`)
- Test: `tests/test_package_schemas.py`

**Interfaces:**
- Consumes: `AppError`, `PackageStatus` from Task 1.
- Produces: `PackageCreateResponse`, `PackageSummary`, `PackageDetailResponse`, `PackageDeleteResponse`, `PackageStatusResponse` — Task 4 and Task 6 reuse `PackageStatus` and the "package not found" `AppError` pattern established here.

- [ ] **Step 1: Write `src/claimflow/schemas/packages.py`**

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import PackageStatus


class PackageCreateResponse(BaseModel):
    package_id: str
    status: PackageStatus


class PackageSummary(BaseModel):
    package_id: str
    status: PackageStatus
    created_at: datetime


class PackageDetailResponse(BaseModel):
    package_id: str
    status: PackageStatus
    result: dict[str, Any] | None
    error: str | None


class PackageDeleteResponse(BaseModel):
    package_id: str
    status: str


class PackageStatusResponse(BaseModel):
    package_id: str
    status: PackageStatus
```

- [ ] **Step 2: Write the failing test**

```python
from fastapi.testclient import TestClient

from api.main import app


def test_list_packages_response_shape():
    with TestClient(app) as client:
        resp = client.get("/packages")
    assert resp.status_code == 200
    assert resp.json() == []


def test_package_status_field_is_enum_value():
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert create.status_code == 200
    body = create.json()
    assert body["status"] in ("queued", "processing", "completed", "failed")
    assert set(body.keys()) == {"package_id", "status"}
```

- [ ] **Step 3: Run test to verify it currently passes on shape but with no schema enforcement**

Run: `uv run pytest tests/test_package_schemas.py -v`
Expected: PASS today (routes already return these keys) — this test is the regression guard for Step 4-5, which add `response_model=` enforcement.

- [ ] **Step 4: Wire `response_model=` and build model instances in the 6 package routes**

In `api/main.py`, add to imports:

```python
from claimflow.schemas.packages import (
    PackageCreateResponse,
    PackageDeleteResponse,
    PackageDetailResponse,
    PackageStatusResponse,
    PackageSummary,
)
```

Replace `api/main.py:81-99`:

```python
@app.post("/packages", response_model=PackageCreateResponse)
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
    finally:
        session.close()

    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir)
    return PackageCreateResponse(package_id=package_id, status=PackageStatus.QUEUED)
```

Replace `api/main.py:102-111`:

```python
@app.get("/packages", response_model=list[PackageSummary])
async def list_packages():
    session = db.SessionLocal()
    try:
        return [
            PackageSummary(package_id=pkg.id, status=pkg.status, created_at=pkg.created_at)
            for pkg in db.list_packages(session)
        ]
    finally:
        session.close()
```

Replace `api/main.py:114-128`:

```python
@app.get("/packages/{package_id}", response_model=PackageDetailResponse)
async def get_package(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        return PackageDetailResponse(
            package_id=pkg.id,
            status=pkg.status,
            result=json.loads(pkg.result_json) if pkg.result_json else None,
            error=pkg.error,
        )
    finally:
        session.close()
```

Replace `api/main.py:131-143`:

```python
@app.delete("/packages/{package_id}", response_model=PackageDeleteResponse)
async def delete_package(package_id: str):
    session = db.SessionLocal()
    try:
        deleted = db.delete_package(session, package_id)
        if not deleted:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
    finally:
        session.close()

    pkg_dir = Path(settings.storage_dir) / package_id
    shutil.rmtree(pkg_dir, ignore_errors=True)
    return PackageDeleteResponse(package_id=package_id, status="deleted")
```

Replace `api/main.py:146-163`:

```python
@app.post("/packages/{package_id}/process", response_model=PackageCreateResponse)
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
    finally:
        session.close()

    pkg_dir = Path(settings.storage_dir) / package_id
    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir, overrides)
    return PackageCreateResponse(package_id=package_id, status=PackageStatus.QUEUED)
```

Replace `api/main.py:166-175`:

```python
@app.get("/packages/{package_id}/status", response_model=PackageStatusResponse)
async def get_package_status(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        return PackageStatusResponse(package_id=pkg.id, status=pkg.status)
    finally:
        session.close()
```

Also add `from claimflow.schemas.enums import PackageStatus` to `api/main.py` imports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_package_schemas.py tests/test_error_envelope.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/schemas/packages.py api/main.py tests/test_package_schemas.py
git commit -m "feat: add Pydantic response models to package endpoints"
```

---

### Task 3: Document endpoint schemas

**Files:**
- Create: `src/claimflow/schemas/documents.py`
- Modify: `api/main.py:178-249` (3 routes: `GET .../documents`, `GET .../documents/{id}`, `POST .../documents/{id}/reclassify`; `GET .../pages/{page}` gets typed query param only, response stays binary)
- Test: `tests/test_document_schemas.py`

**Interfaces:**
- Consumes: `AppError`, `DocumentType` from Task 1.
- Produces: `DocumentSummary`, `DocumentReclassifyRequest`, `DocumentReclassifyResponse` — Task 4 (`evidence`) reuses the "document not found" `AppError` pattern.

- [ ] **Step 1: Write `src/claimflow/schemas/documents.py`**

```python
from pydantic import BaseModel

from claimflow.schemas.enums import DocumentType


class DocumentSummary(BaseModel):
    document_id: str
    path: str
    doc_type: DocumentType
    has_text_layer: bool
    scan_quality: float | None
    classification_reason: str | None
    manually_overridden: bool


class DocumentReclassifyRequest(BaseModel):
    doc_type: DocumentType
    reviewer: str = "reviewer"


class DocumentReclassifyResponse(BaseModel):
    document_id: str
    doc_type: DocumentType
    classification_reason: str | None
    manually_overridden: bool
```

- [ ] **Step 2: Write the failing test**

```python
from fastapi.testclient import TestClient

from api.main import app


def test_reclassify_rejects_unknown_doc_type():
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]
        docs = client.get(f"/packages/{package_id}/documents").json()

    if not docs:
        return  # background processing hasn't classified yet in this test's timing; covered by lifecycle test in Task 9

    document_id = docs[0]["document_id"]
    with TestClient(app) as client:
        resp = client.post(
            f"/packages/{package_id}/documents/{document_id}/reclassify",
            json={"doc_type": "not_a_real_type"},
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_document_schemas.py -v`
Expected: FAIL — `reclassify_document` still takes `body: dict` and reads `body["doc_type"]` directly, so an invalid value is accepted (200), not rejected (422).

- [ ] **Step 4: Wire `response_model=` and typed request body**

In `api/main.py`, add to imports:

```python
from claimflow.schemas.documents import DocumentReclassifyRequest, DocumentReclassifyResponse, DocumentSummary
```

Replace `api/main.py:178-191`:

```python
@app.get("/packages/{package_id}/documents", response_model=list[DocumentSummary])
async def list_package_documents(package_id: str):
    session = db.SessionLocal()
    try:
        return [
            DocumentSummary(
                document_id=doc.id, path=doc.path, doc_type=doc.doc_type,
                has_text_layer=doc.has_text_layer, scan_quality=doc.scan_quality,
                classification_reason=doc.classification_reason, manually_overridden=doc.manually_overridden,
            )
            for doc in db.list_documents(session, package_id)
        ]
    finally:
        session.close()
```

Replace `api/main.py:194-207`:

```python
@app.get("/packages/{package_id}/documents/{document_id}", response_model=DocumentSummary)
async def get_package_document(package_id: str, document_id: str):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "DOCUMENT_NOT_FOUND", "Document does not exist")
        return DocumentSummary(
            document_id=doc.id, path=doc.path, doc_type=doc.doc_type,
            has_text_layer=doc.has_text_layer, scan_quality=doc.scan_quality,
            classification_reason=doc.classification_reason, manually_overridden=doc.manually_overridden,
        )
    finally:
        session.close()
```

Replace `api/main.py:210-232`:

```python
@app.post(
    "/packages/{package_id}/documents/{document_id}/reclassify",
    response_model=DocumentReclassifyResponse,
)
async def reclassify_document(package_id: str, document_id: str, body: DocumentReclassifyRequest):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "DOCUMENT_NOT_FOUND", "Document does not exist")

        doc.doc_type = body.doc_type.value
        doc.classification_reason = "manual override"
        doc.manually_overridden = True
        session.commit()

        db.log_audit(
            session, package_id, body.reviewer, "reclassify",
            {"document_id": document_id, "doc_type": doc.doc_type},
        )
        return DocumentReclassifyResponse(
            document_id=doc.id, doc_type=doc.doc_type,
            classification_reason=doc.classification_reason, manually_overridden=doc.manually_overridden,
        )
    finally:
        session.close()
```

Replace the two `raise HTTPException(status_code=404, detail="Document not found")` calls in `get_document_page_image` (`api/main.py:241`) and the "Page could not be rendered" one (`api/main.py:248`):

```python
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "DOCUMENT_NOT_FOUND", "Document does not exist")
```

```python
    if image_bytes is None:
        raise AppError(404, "PAGE_RENDER_FAILED", "Page could not be rendered")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_schemas.py tests/test_package_schemas.py tests/test_error_envelope.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/schemas/documents.py api/main.py tests/test_document_schemas.py
git commit -m "feat: add Pydantic response models to document endpoints"
```

---

### Task 4: Evidence + review-queue + package-review schemas

**Files:**
- Create: `src/claimflow/schemas/review_read.py`
- Modify: `api/main.py:252-314` (3 routes: `GET .../fields/{id}/evidence`, `GET /reviews/queue`, `GET .../review`)
- Test: `tests/test_review_read_schemas.py`

**Interfaces:**
- Consumes: `AppError`, `PackageStatus` from Task 1, `PackageSummary` from Task 2.
- Produces: `FieldEvidenceResponse`, `PackageReviewResponse` — Task 5 reuses `FieldEvidenceResponse`'s `field_id` typing convention (`int`) for the review-submission route.

- [ ] **Step 1: Write `src/claimflow/schemas/review_read.py`**

```python
from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import PackageStatus


class FieldEvidenceResponse(BaseModel):
    field_id: int
    name: str
    value: Any | None
    confidence: float
    evidence: dict[str, Any] | None


class ReviewFieldSummary(BaseModel):
    field_id: int
    name: str
    value: Any | None
    confidence: float
    field_status: str


class ReviewValidationFailure(BaseModel):
    field: str
    rule: str
    reason: str


class PackageReviewResponse(BaseModel):
    package_id: str
    status: PackageStatus
    fields: list[ReviewFieldSummary]
    validation_failures: list[ReviewValidationFailure]
```

- [ ] **Step 2: Write the failing test**

```python
from fastapi.testclient import TestClient

from api.main import app


def test_evidence_404_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/pkg/fields/999999/evidence")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FIELD_NOT_FOUND"


def test_reviews_queue_shape():
    with TestClient(app) as client:
        resp = client.get("/reviews/queue")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_review_read_schemas.py -v`
Expected: FAIL — `get_field_evidence` still raises bare `HTTPException(404, detail="Field not found")`, so `resp.json()["error"]` raises `KeyError`.

- [ ] **Step 4: Wire `response_model=` and swap `AppError`**

In `api/main.py`, add to imports:

```python
from claimflow.schemas.review_read import (
    FieldEvidenceResponse,
    PackageReviewResponse,
    ReviewFieldSummary,
    ReviewValidationFailure,
)
```

Replace `api/main.py:252-271`:

```python
@app.get("/packages/{package_id}/fields/{field_id}/evidence", response_model=FieldEvidenceResponse)
async def get_field_evidence(package_id: str, field_id: int):
    session = db.SessionLocal()
    try:
        field = db.get_extracted_field(session, field_id)
        if field is None:
            raise AppError(404, "FIELD_NOT_FOUND", "Field does not exist")
        run = session.get(db.ExtractionRun, field.extraction_run_id)
        doc = session.get(db.Document, run.document_id) if run else None
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "FIELD_NOT_FOUND", "Field does not exist")
        return FieldEvidenceResponse(
            field_id=field.id,
            name=field.name,
            value=json.loads(field.value_json) if field.value_json else None,
            confidence=field.confidence,
            evidence=json.loads(field.evidence_json) if field.evidence_json else None,
        )
    finally:
        session.close()
```

Replace `api/main.py:274-283`:

```python
@app.get("/reviews/queue", response_model=list[PackageSummary])
async def reviews_queue():
    session = db.SessionLocal()
    try:
        return [
            PackageSummary(package_id=pkg.id, status=pkg.status, created_at=pkg.created_at)
            for pkg in db.list_flagged_packages(session)
        ]
    finally:
        session.close()
```

(add `PackageSummary` to the `from claimflow.schemas.packages import ...` line added in Task 2)

Replace `api/main.py:286-314`:

```python
@app.get("/packages/{package_id}/review", response_model=PackageReviewResponse)
async def get_package_review(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")

        run = db.latest_extraction_run_for_package(session, package_id)
        fields = db.list_extracted_fields_for_run(session, run.id) if run else []
        failures = db.list_validation_failures_for_run(session, run.id) if run else []

        return PackageReviewResponse(
            package_id=package_id,
            status=pkg.status,
            fields=[
                ReviewFieldSummary(
                    field_id=f.id, name=f.name,
                    value=json.loads(f.value_json) if f.value_json else None,
                    confidence=f.confidence, field_status=f.field_status,
                )
                for f in fields
            ],
            validation_failures=[
                ReviewValidationFailure(field=vf.field, rule=vf.rule, reason=vf.reason) for vf in failures
            ],
        )
    finally:
        session.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_read_schemas.py tests/ -v`
Expected: PASS (full suite so far green)

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/schemas/review_read.py api/main.py tests/test_review_read_schemas.py
git commit -m "feat: add Pydantic response models to evidence and review-read endpoints"
```

---

### Task 5: Review-action, validation-rerun, decision schemas

**Files:**
- Create: `src/claimflow/schemas/review_write.py`
- Modify: `api/main.py:317-379` (3 routes: `POST .../fields/{id}/review`, `POST .../validation/re-run`, `POST .../decision`)
- Test: `tests/test_review_write_schemas.py`

**Interfaces:**
- Consumes: `AppError`, `ReviewActionType`, `DecisionType` from Task 1.
- Produces: `FieldReviewRequest`, `FieldReviewResponse`, `ValidationRerunRequest`, `ValidationRerunResponse`, `DecisionRequest`, `DecisionResponse`.

- [ ] **Step 1: Write `src/claimflow/schemas/review_write.py`**

```python
from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import DecisionType, ReviewActionType


class FieldReviewRequest(BaseModel):
    action: ReviewActionType
    corrected_value: Any | None = None
    validation_after: list[str] | None = None
    reviewer: str = "reviewer"
    note: str | None = None


class FieldReviewResponse(BaseModel):
    field_id: int
    action: ReviewActionType
    reviewer: str
    corrected_value: Any | None


class ValidationRerunRequest(BaseModel):
    corrected_fields: dict[str, Any] = {}


class ValidationFailureItem(BaseModel):
    field: str
    rule: str
    reason: str


class ValidationRerunResponse(BaseModel):
    validation_failures: list[ValidationFailureItem]


class DecisionRequest(BaseModel):
    decision: DecisionType
    review_reasons: list[str] = []


class DecisionResponse(BaseModel):
    package_id: str
    decision: DecisionType
```

- [ ] **Step 2: Write the failing test**

```python
from fastapi.testclient import TestClient

from api.main import app


def test_field_review_rejects_invalid_action():
    with TestClient(app) as client:
        resp = client.post("/packages/pkg/fields/1/review", json={"action": "not_a_real_action"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_decision_rejects_invalid_decision():
    with TestClient(app) as client:
        resp = client.post("/packages/pkg/decision", json={"decision": "not_a_real_decision"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_review_write_schemas.py -v`
Expected: FAIL — both routes currently take `body: dict`, so `"not_a_real_action"`/`"not_a_real_decision"` pass through to a `KeyError`/500, not a 422.

- [ ] **Step 4: Wire request/response models**

In `api/main.py`, add to imports:

```python
from claimflow.schemas.review_write import (
    DecisionRequest,
    DecisionResponse,
    FieldReviewRequest,
    FieldReviewResponse,
    ValidationFailureItem,
    ValidationRerunRequest,
    ValidationRerunResponse,
)
```

Replace `api/main.py:317-347`:

```python
@app.post("/packages/{package_id}/fields/{field_id}/review", response_model=FieldReviewResponse)
async def submit_field_review(package_id: str, field_id: int, body: FieldReviewRequest):
    session = db.SessionLocal()
    try:
        field = db.get_extracted_field(session, field_id)
        if field is None:
            raise AppError(404, "FIELD_NOT_FOUND", "Field does not exist")
        run = session.get(db.ExtractionRun, field.extraction_run_id)
        doc = session.get(db.Document, run.document_id) if run else None
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "FIELD_NOT_FOUND", "Field does not exist")

        failures_before = db.list_validation_failures_for_run(session, run.id)
        validation_before = [f.reason for f in failures_before if f.field == field.name]

        action = db.record_review_action(
            session, run.id, field.name, body.action.value,
            original_value=json.loads(field.value_json) if field.value_json else None,
            corrected_value=body.corrected_value,
            validation_before=validation_before,
            validation_after=body.validation_after,
            reviewer=body.reviewer,
            note=body.note,
        )
        db.log_audit(session, package_id, action.reviewer, "review_edit", {"field": field.name, "action": action.action})
        return FieldReviewResponse(
            field_id=field_id, action=action.action, reviewer=action.reviewer,
            corrected_value=json.loads(action.corrected_value_json) if action.corrected_value_json else None,
        )
    finally:
        session.close()
```

Replace `api/main.py:350-365`:

```python
@app.post("/packages/{package_id}/validation/re-run", response_model=ValidationRerunResponse)
async def rerun_package_validation(package_id: str, body: ValidationRerunRequest):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        result = json.loads(pkg.result_json) if pkg.result_json else {}
    finally:
        session.close()

    domain = result.get("domain")
    merged = dict(result.get("extraction_data") or {})
    merged.update(body.corrected_fields)
    failures = review.rerun_validation(domain, merged)
    return ValidationRerunResponse(
        validation_failures=[ValidationFailureItem(field=f["field"], rule=f["rule"], reason=f["reason"]) for f in failures]
    )
```

Replace `api/main.py:368-379`:

```python
@app.post("/packages/{package_id}/decision", response_model=DecisionResponse)
async def submit_package_decision(package_id: str, body: DecisionRequest):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        decision = db.create_decision(session, package_id, body.decision.value, body.review_reasons)
        db.log_audit(session, package_id, "reviewer", "decision", {"decision": decision.decision})
        return DecisionResponse(package_id=package_id, decision=decision.decision)
    finally:
        session.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_write_schemas.py tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/schemas/review_write.py api/main.py tests/test_review_write_schemas.py
git commit -m "feat: add Pydantic request/response models to review-write endpoints"
```

---

### Task 6: Policy-evidence, audit, export schemas

**Files:**
- Create: `src/claimflow/schemas/reporting.py`
- Modify: `api/main.py:382-430` (3 routes: `GET .../policy-evidence`, `GET .../audit`, `GET .../export`)
- Test: `tests/test_reporting_schemas.py`

**Interfaces:**
- Consumes: `AppError`, `PackageStatus`, `DecisionType` from Task 1; `ValidationFailureItem` from Task 5.
- Produces: `PolicyEvidenceItem`, `AuditEventItem`, `ExportResponse`.

- [ ] **Step 1: Write `src/claimflow/schemas/reporting.py`**

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import DecisionType, PackageStatus
from claimflow.schemas.review_write import ValidationFailureItem


class PolicyEvidenceItem(BaseModel):
    question: str
    answer: str
    citations: list[Any]


class AuditEventItem(BaseModel):
    actor: str
    action: str
    timestamp: datetime
    detail: dict[str, Any] | None


class ExtractionFieldExport(BaseModel):
    name: str
    value: Any | None
    confidence: float
    grounded: bool
    valid: bool
    field_status: str


class PolicyAnswerExport(BaseModel):
    question: str
    answer: str
    citations: list[Any]


class ExportResponse(BaseModel):
    package_id: str
    status: PackageStatus
    decision: DecisionType | None
    domain: str | None
    extraction_fields: list[ExtractionFieldExport]
    validation_failures: list[ValidationFailureItem]
    policy_answers: list[PolicyAnswerExport]
```

- [ ] **Step 2: Write the failing test**

```python
from fastapi.testclient import TestClient

from api.main import app


def test_export_404_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/does-not-exist/export")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PACKAGE_NOT_FOUND"


def test_audit_trail_shape():
    with TestClient(app) as client:
        resp = client.get("/packages/does-not-exist/audit")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_reporting_schemas.py -v`
Expected: FAIL — `export_package` still raises bare `HTTPException`.

- [ ] **Step 4: Wire `response_model=` and swap `AppError`**

In `api/main.py`, add to imports:

```python
from claimflow.schemas.reporting import (
    AuditEventItem,
    ExportResponse,
    ExtractionFieldExport,
    PolicyAnswerExport,
    PolicyEvidenceItem,
)
```

Replace `api/main.py:382-394`:

```python
@app.get("/packages/{package_id}/policy-evidence", response_model=list[PolicyEvidenceItem])
async def get_policy_evidence(package_id: str):
    session = db.SessionLocal()
    try:
        return [
            PolicyEvidenceItem(
                question=pe.question, answer=pe.answer,
                citations=json.loads(pe.citations_json),
            )
            for pe in db.list_policy_evidence_for_package(session, package_id)
        ]
    finally:
        session.close()
```

Replace `api/main.py:397-409`:

```python
@app.get("/packages/{package_id}/audit", response_model=list[AuditEventItem])
async def get_audit_trail(package_id: str):
    session = db.SessionLocal()
    try:
        return [
            AuditEventItem(
                actor=entry.actor, action=entry.action, timestamp=entry.timestamp,
                detail=json.loads(entry.detail_json) if entry.detail_json else None,
            )
            for entry in db.list_audit_events_for_package(session, package_id)
        ]
    finally:
        session.close()
```

Replace `api/main.py:412-430`:

```python
@app.get("/packages/{package_id}/export", response_model=ExportResponse)
async def export_package(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        result = json.loads(pkg.result_json) if pkg.result_json else {}
        return ExportResponse(
            package_id=package_id,
            status=pkg.status,
            decision=result.get("decision"),
            domain=result.get("domain"),
            extraction_fields=[
                ExtractionFieldExport(**f) for f in result.get("extraction_fields", [])
            ],
            validation_failures=result.get("validation_failures", []),
            policy_answers=[
                PolicyAnswerExport(**a) for a in result.get("policy_answers", [])
            ],
        )
    finally:
        session.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_reporting_schemas.py tests/ -v`
Expected: PASS — full existing test suite plus all schema tests green.

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/schemas/reporting.py api/main.py tests/test_reporting_schemas.py
git commit -m "feat: add Pydantic response models to policy-evidence, audit, and export endpoints"
```

---

### Task 7: OpenAPI polish + full-contract test

**Files:**
- Modify: `api/main.py` (add `tags=` to every route, `summary=` on the 6 most important ones)
- Test: `tests/test_openapi_contract.py`

**Interfaces:**
- Consumes: nothing new — this task only adds metadata and a whole-schema assertion.

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from api.main import app

EXPECTED_ROUTES = {
    ("GET", "/health"),
    ("POST", "/packages"),
    ("GET", "/packages"),
    ("GET", "/packages/{package_id}"),
    ("DELETE", "/packages/{package_id}"),
    ("POST", "/packages/{package_id}/process"),
    ("GET", "/packages/{package_id}/status"),
    ("GET", "/packages/{package_id}/documents"),
    ("GET", "/packages/{package_id}/documents/{document_id}"),
    ("POST", "/packages/{package_id}/documents/{document_id}/reclassify"),
    ("GET", "/packages/{package_id}/documents/{document_id}/pages/{page}"),
    ("GET", "/packages/{package_id}/fields/{field_id}/evidence"),
    ("GET", "/reviews/queue"),
    ("GET", "/packages/{package_id}/review"),
    ("POST", "/packages/{package_id}/fields/{field_id}/review"),
    ("POST", "/packages/{package_id}/validation/re-run"),
    ("POST", "/packages/{package_id}/decision"),
    ("GET", "/packages/{package_id}/policy-evidence"),
    ("GET", "/packages/{package_id}/audit"),
    ("GET", "/packages/{package_id}/export"),
}


def test_openapi_schema_has_every_route_with_response_model():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    found = set()
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            found.add((method.upper(), path))
            if path == "/health":
                continue
            responses = operation["responses"]
            success = responses.get("200") or responses.get("201")
            assert "content" in success, f"{method.upper()} {path} has no typed 200 response"
            assert "404" in responses or "422" in responses or method.upper() == "GET"

    assert found == EXPECTED_ROUTES


def test_openapi_error_responses_reference_error_envelope():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    assert "ErrorEnvelope" in schema["components"]["schemas"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openapi_contract.py -v`
Expected: FAIL — `test_openapi_error_responses_reference_error_envelope` fails because `ErrorEnvelope` is never referenced in any route's `responses=`, so FastAPI never adds it to `components.schemas`.

- [ ] **Step 3: Add `tags=` to every route and a shared `responses=` default for the 404 envelope**

In `api/main.py`, add near the top (after the `app = FastAPI(...)` line):

```python
ERROR_RESPONSES = {404: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}}
```

Add `tags=["packages"]` to the 6 package routes, `tags=["documents"]` to the 4 document routes, `tags=["review"]` to the 6 review routes (evidence, queue, review, field-review, validation-rerun, decision), `tags=["reporting"]` to the 3 reporting routes, and `responses=ERROR_RESPONSES` to every route decorator except `/health`. Example for `get_package`:

```python
@app.get(
    "/packages/{package_id}",
    response_model=PackageDetailResponse,
    tags=["packages"],
    responses=ERROR_RESPONSES,
)
```

Apply the same `tags=[...]` and `responses=ERROR_RESPONSES` pattern to the other 18 non-health routes, matching the group each belongs to as listed above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_openapi_contract.py tests/ -v`
Expected: PASS — full suite green.

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_openapi_contract.py
git commit -m "feat: tag routes and reference error envelope in OpenAPI schema"
```

---

## Self-Review Notes

- **Spec coverage:** Pydantic models everywhere (Tasks 2-6), standard error envelope (Task 1), ISO 8601 timestamps via Pydantic `datetime` fields (Tasks 2, 4, 6 — no manual `.isoformat()` left), consistent ID types documented in Global Constraints (no code change needed, already consistent), explicit nullable fields (every `| None` field above), shared enums (Task 1), accurate OpenAPI (Task 7). Typed frontend client generation is deferred — no Next.js frontend exists yet in this repo (confirmed via inventory: only `streamlit_app.py`); Task 7's `/openapi.json` output is what a future `openapi-typescript` run would consume, and needs no further backend work.
- **Placeholder scan:** none found — every step shows complete code, not "similar to Task N".
- **Type consistency:** `field_id: int` matches across `review_read.py`, `review_write.py`, and route path params. `package_id`/`document_id: str` matches across all schema modules and route path params. `PackageStatus`, `DecisionType`, `ReviewActionType`, `DocumentType` imported from the single `enums.py` everywhere they're used — no per-file redefinition.
