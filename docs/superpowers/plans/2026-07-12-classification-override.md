# Classification Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a reviewer override a document's classified type (e.g. `unknown` → `cms1500`, `medical_bill` → `eob`) and reprocess the package so the new type's schema and validators actually run. Backend only — no UI, per explicit instruction; the UI work is a separate, later effort.

**Architecture:** `_classify_doc_type` in `ingest.py` currently returns just a `doc_type` string with no record of *why*. It's changed to also return a human-readable reason string, which flows into a new `Document.classification_reason` column (persistence layer, already built) alongside a new `Document.manually_overridden` boolean. A new endpoint lets a reviewer set a document's `doc_type` directly, marking it overridden. `ingest_node` gains an optional `doc_type_overrides: dict[str, str]` (filename → forced type) it reads from `ClaimState` — when present for a file, it skips keyword classification for that file and uses the override instead, tagging the reason `"manual override"`. `POST /packages/{package_id}/process` (already built) is extended to look up any manually-overridden documents for the package and pass them through as `doc_type_overrides`, so a reprocess after an override actually re-runs `extract_node` against the new domain's schema — the classification override changes the document's type, which can change the package's detected `domain`, which changes which `SchemaSpec` `extract_node` looks up via `get_domain(domain_key)`.

**Tech Stack:** No new dependencies.

## Global Constraints

- No UI. This plan is API + engine only.
- `_classify_doc_type` changes its return type from `str` to `tuple[str, str | None]` (`doc_type`, `reason`). Every caller must be updated in the same task that changes the signature — no partial migration.
- `IngestedDoc` (in `src/claimflow/state.py`) gains `classification_reason: str | None`. `Document` (in `src/claimflow/db.py`) gains `classification_reason: str | None` and `manually_overridden: bool = False` (default `False`).
- `ClaimState` gains `doc_type_overrides: dict[str, str]` — optional in practice (`ingest_node` reads it via `state.get("doc_type_overrides") or {}`, so existing test fixtures and callers that don't set it keep working unchanged).
- `data/claimflow.db` is disposable dev state (gitignored, no migration tool, per the persistence-layer plan's established constraint) — adding new `Document` columns only takes effect on a fresh DB file; this is an accepted, already-established limitation, not something this plan needs to solve.
- The override endpoint changes ONE document's classification. It does not itself decide whether the package's overall `domain` should change — that's `ingest_node`'s job on the next reprocess, using the same domain-detection logic it already has (first document whose `doc_type` matches a registered domain key becomes `detected_domain`).
- `POST /packages/{package_id}/documents/{document_id}/reclassify` only sets fields on the `Document` row — it does not itself trigger reprocessing. The reviewer calls the existing `POST /packages/{package_id}/process` afterward to actually reprocess with the new classification. Keeping these separate matches the existing `process`/`status` split from the API-expansion plan.
- **Known limitation, accepted for this plan:** the override lookup matches by filename (`Path(doc.path).name`, built from the stored `Document.path`, matched against `src_path.name` in `ingest_node` on reprocess). For a DOCX source, `Document.path` is the *converted* PDF's path (e.g. `application.pdf`, in `.converted/`), while `ingest_node` re-reads the *original* uploaded filename (`application.docx`) from the package directory on every run — these don't match, so an override on a DOCX-derived document silently won't apply on reprocess. This is a real gap at the intersection of two separate features (DOCX conversion, added earlier; classification override, this plan) and is not fixed here — tracked as a known limitation, not silently shipped as a working feature for that input type. PDF/image uploads (the tested, common case) are unaffected — `Document.path` equals the original filename for those.

---

## File Structure

- **Modify: `src/claimflow/nodes/ingest.py`** — `_classify_doc_type` returns `(doc_type, reason)`; `ingest_node` reads `doc_type_overrides` from state and stores `classification_reason` on each `IngestedDoc`.
- **Modify: `src/claimflow/state.py`** — `IngestedDoc` gains `classification_reason`; `ClaimState` gains `doc_type_overrides`.
- **Modify: `src/claimflow/db.py`** — `Document` model gains `classification_reason`, `manually_overridden`; `create_document` persists them.
- **Modify: `api/main.py`** — new `POST /packages/{package_id}/documents/{document_id}/reclassify` endpoint; `process_package` looks up overridden documents and passes them through; documents endpoints' responses include the two new fields.
- **Modify: `README.md`** — document the override endpoint and the reclassify → reprocess flow.

---

## Task 1: Classification reason — `_classify_doc_type` returns why it matched

**Files:**
- Modify: `src/claimflow/nodes/ingest.py`
- Modify: `src/claimflow/state.py`
- Test: `tests/test_graph.py`, `tests/test_new_domains.py`

**Interfaces:**
- Consumes: `all_domains()` (unchanged), `Domain.keywords`/`Domain.supporting_types` (unchanged).
- Produces: `_classify_doc_type(text: str) -> tuple[str, str | None]` — the reason string is consumed by Task 3's persistence and the reclassify endpoint's response shape.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_new_domains.py` (this file already tests `_classify_doc_type` directly):

```python
def test_classify_doc_type_returns_reason():
    from claimflow.nodes.ingest import _classify_doc_type

    doc_type, reason = _classify_doc_type("HEALTH INSURANCE CLAIM FORM CMS-1500")
    assert doc_type == "cms1500"
    assert reason is not None
    assert "cms-1500" in reason.lower() or "cms1500" in reason.lower()

    doc_type, reason = _classify_doc_type("This is an Explanation of Benefits. This is not a bill.")
    assert doc_type == "eob"
    assert reason is not None

    doc_type, reason = _classify_doc_type("completely unrecognizable text with no keywords")
    assert doc_type == "unknown"
    assert reason is None
```

The existing tests in this file (e.g. `assert _classify_doc_type("...") == "eob"`) will break with this change — that's expected, fix them in Step 3 alongside the implementation (they become `assert _classify_doc_type("...")[0] == "eob"`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_new_domains.py::test_classify_doc_type_returns_reason -v`
Expected: FAIL — `_classify_doc_type` still returns a bare string, so `doc_type, reason = _classify_doc_type(...)` raises `ValueError: too many values to unpack` or similar (a string is iterable character-by-character, so this actually unpacks the first two characters — assert on `doc_type == "cms1500"` will fail since `doc_type` will be a single character).

- [ ] **Step 3: Update `_classify_doc_type` and all its callers**

In `src/claimflow/nodes/ingest.py`, replace `_classify_doc_type`:

```python
def _classify_doc_type(text: str) -> tuple[str, str | None]:
    """Classify a document into a specific type, and say why. A domain's main form
    takes priority over supporting-document subtypes, so generic terms in a
    supporting doc can't steal the match away from the form itself. Returns
    (doc_type, reason) — reason is None only for "unknown"."""
    lower = text.lower()
    for domain in all_domains():
        for kw in domain.keywords:
            if kw in lower:
                return domain.doc_type, f"matched domain keyword '{kw}' for {domain.doc_type}"
    for domain in all_domains():
        for subtype, keywords in domain.supporting_types.items():
            for kw in keywords:
                if kw in lower:
                    return subtype, f"matched supporting keyword '{kw}' for {subtype}"
    return "unknown", None
```

Update `ingest_node`'s call site (currently `doc_type = _classify_doc_type(first_page_text)`) to:

```python
            doc_type, classification_reason = _classify_doc_type(first_page_text)
```

and update the `docs.append(IngestedDoc(...))` call to include the new field:

```python
            docs.append(IngestedDoc(
                path=str(pdf_path), doc_type=doc_type,
                has_text_layer=has_text, scan_quality=scan_quality,
                classification_reason=classification_reason,
            ))
```

Also update the `except Exception:` fallback's `IngestedDoc(...)` call to include `classification_reason=None`.

In `src/claimflow/state.py`, add the new field to `IngestedDoc`:

```python
class IngestedDoc(TypedDict):
    path: str
    doc_type: str
    has_text_layer: bool
    scan_quality: float | None
    classification_reason: str | None   # why this doc_type was assigned; None for "unknown" or manual override not yet set
```

Fix the existing tests in `tests/test_new_domains.py` that call `_classify_doc_type(...)` expecting a bare string — change each `assert _classify_doc_type("...") == "some_type"` to `assert _classify_doc_type("...")[0] == "some_type"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_new_domains.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Fix the graph tests that construct `IngestedDoc`-shaped dicts**

Run: `uv run pytest tests/test_graph.py -v`
Expected: Any test asserting on `docs[0]["doc_type"]` etc. should still pass unchanged (dict key access, not affected by the new key's presence). If any test explicitly constructs a full `IngestedDoc` literal expecting an exact set of keys, add `"classification_reason": ...` to it. Fix any such failures found.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/claimflow/nodes/ingest.py src/claimflow/state.py tests/test_new_domains.py tests/test_graph.py
git commit -m "feat: classify_doc_type also returns why a document matched"
```

---

## Task 2: `doc_type_overrides` — let ingest skip classification for specific files

**Files:**
- Modify: `src/claimflow/nodes/ingest.py`
- Modify: `src/claimflow/state.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: nothing new from other modules.
- Produces: `ingest_node` now reads `state.get("doc_type_overrides")` — a `dict[str, str]` mapping a source filename (e.g. `"claim.pdf"`) to a forced `doc_type` — consumed by Task 3's API wiring, which builds this dict from `Document.manually_overridden` rows before calling `_run_claim`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_graph.py`:

```python
def test_ingest_node_respects_doc_type_override(tmp_path):
    """A filename present in doc_type_overrides skips keyword classification entirely."""
    from unittest.mock import MagicMock, patch

    pkg = tmp_path / "package"
    pkg.mkdir()
    claim_pdf = pkg / "claim.pdf"
    claim_pdf.write_bytes(b"placeholder")

    fake_page = MagicMock()
    fake_page.text = "completely unrecognizable text with no keywords"
    fake_page.native_text_available = True
    fake_page.ocr_used = False
    fake_artifact = MagicMock()
    fake_artifact.pages = [fake_page]

    with patch("claimflow.nodes.ingest.build_artifact", return_value=fake_artifact):
        from claimflow.nodes.ingest import ingest_node
        from claimflow.state import ClaimState

        state: ClaimState = {
            "package_dir": str(pkg),
            "documents": [],
            "extraction_data": None,
            "extraction_fields": None,
            "extraction_status": None,
            "extraction_overall_confidence": None,
            "validation_failures": [],
            "policy_answers": [],
            "decision": None,
            "review_reasons": [],
            "error": None,
            "doc_type_overrides": {"claim.pdf": "cms1500"},
        }
        result = ingest_node(state)

    docs = result["documents"]
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "cms1500"
    assert docs[0]["classification_reason"] == "manual override"
    assert result["domain"] == "cms1500"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py::test_ingest_node_respects_doc_type_override -v`
Expected: FAIL — `docs[0]["doc_type"]` is `"unknown"` (the override is ignored, since `ingest_node` doesn't read `doc_type_overrides` yet).

- [ ] **Step 3: Wire the override into `ingest_node`**

In `src/claimflow/nodes/ingest.py`, at the top of `ingest_node` (right after `domain_keys = {d.doc_type for d in all_domains()}`), add:

```python
    overrides: dict[str, str] = state.get("doc_type_overrides") or {}
```

Then change the classification call site from:

```python
            doc_type, classification_reason = _classify_doc_type(first_page_text)
```

to:

```python
            if name in overrides:
                doc_type, classification_reason = overrides[name], "manual override"
            else:
                doc_type, classification_reason = _classify_doc_type(first_page_text)
```

In `src/claimflow/state.py`, add the new field to `ClaimState` (after the `domain` field):

```python
    domain: str | None      # detected doc_type, e.g. "cms1500" | "xactimate" | "loan"
    doc_type_overrides: dict[str, str]   # filename -> forced doc_type, from a reviewer's classification override
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py::test_ingest_node_respects_doc_type_override -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: All pass — existing test fixtures that construct `ClaimState` dicts without `doc_type_overrides` still work, since `ingest_node` uses `state.get("doc_type_overrides") or {}`.

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/nodes/ingest.py src/claimflow/state.py tests/test_graph.py
git commit -m "feat: let ingest_node skip classification for reviewer-overridden documents"
```

---

## Task 3: Persist classification metadata; add the reclassify endpoint

**Files:**
- Modify: `src/claimflow/db.py`
- Modify: `api/main.py`
- Test: `tests/test_db.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `IngestedDoc.classification_reason` (Task 1), `ClaimState.doc_type_overrides` (Task 2), existing `db.list_documents`, `db.get_document`.
- Produces: `Document.classification_reason`, `Document.manually_overridden` columns; `create_document` persists them from the `doc` dict; `POST /packages/{package_id}/documents/{document_id}/reclassify` endpoint; `process_package` passes overrides through to `_run_claim`.

- [ ] **Step 1: Write the failing test for the DB layer**

Append to `tests/test_db.py`:

```python
def test_create_document_persists_classification_reason():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    doc = db.create_document(session, pkg.id, {
        "path": "/tmp/claim.pdf", "doc_type": "cms1500", "has_text_layer": True,
        "scan_quality": None, "classification_reason": "matched domain keyword 'cms-1500' for cms1500",
    })
    assert doc.classification_reason == "matched domain keyword 'cms-1500' for cms1500"
    assert doc.manually_overridden is False

    overridden = db.create_document(session, pkg.id, {
        "path": "/tmp/other.pdf", "doc_type": "eob", "has_text_layer": True,
        "scan_quality": None, "classification_reason": "manual override", "manually_overridden": True,
    })
    assert overridden.manually_overridden is True
    session.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_create_document_persists_classification_reason -v`
Expected: FAIL — `AttributeError: 'Document' object has no attribute 'classification_reason'`.

- [ ] **Step 3: Add the columns and update `create_document`**

In `src/claimflow/db.py`, update the `Document` model:

```python
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    path: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String)
    has_text_layer: Mapped[bool] = mapped_column(Boolean)
    scan_quality: Mapped[float | None] = mapped_column(Float, default=None)
    classification_reason: Mapped[str | None] = mapped_column(Text, default=None)
    manually_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
```

Update `create_document`:

```python
def create_document(session: Session, package_id: str, doc: dict) -> Document:
    row = Document(
        id=str(uuid.uuid4()),
        package_id=package_id,
        path=doc["path"],
        doc_type=doc["doc_type"],
        has_text_layer=doc["has_text_layer"],
        scan_quality=doc.get("scan_quality"),
        classification_reason=doc.get("classification_reason"),
        manually_overridden=doc.get("manually_overridden", False),
    )
    session.add(row)
    session.commit()
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Write the failing test for the reclassify endpoint**

Append to `tests/test_api.py`:

```python
def test_reclassify_document():
    from api.main import app
    from claimflow import db

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": None,
        "documents": [{"path": "/tmp/claim.pdf", "doc_type": "unknown", "has_text_layer": True,
                        "scan_quality": None, "classification_reason": None}],
        "extraction_fields": [], "extraction_status": None, "extraction_overall_confidence": None,
        "validation_failures": [], "policy_answers": [], "decision": None, "review_reasons": [], "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            package_id = response.json()["package_id"]

            docs = client.get(f"/packages/{package_id}/documents").json()
            document_id = docs[0]["document_id"]

            reclassify_response = client.post(
                f"/packages/{package_id}/documents/{document_id}/reclassify",
                json={"doc_type": "cms1500", "reviewer": "jane"},
            )

    assert reclassify_response.status_code == 200
    body = reclassify_response.json()
    assert body["doc_type"] == "cms1500"
    assert body["manually_overridden"] is True

    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        assert doc.doc_type == "cms1500"
        assert doc.classification_reason == "manual override"
        assert doc.manually_overridden is True
    finally:
        session.close()


def test_reclassify_document_404_for_wrong_package():
    from api.main import app
    with TestClient(app) as client:
        response = client.post(
            "/packages/wrong-package/documents/does-not-exist/reclassify",
            json={"doc_type": "cms1500"},
        )
    assert response.status_code == 404


def test_reprocess_passes_overrides_to_graph():
    from api.main import app
    from claimflow import db

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": None,
        "documents": [{"path": "/tmp/claim.pdf", "doc_type": "unknown", "has_text_layer": True,
                        "scan_quality": None, "classification_reason": None}],
        "extraction_fields": [], "extraction_status": None, "extraction_overall_confidence": None,
        "validation_failures": [], "policy_answers": [], "decision": None, "review_reasons": [], "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            package_id = response.json()["package_id"]

            docs = client.get(f"/packages/{package_id}/documents").json()
            document_id = docs[0]["document_id"]
            client.post(
                f"/packages/{package_id}/documents/{document_id}/reclassify",
                json={"doc_type": "cms1500"},
            )

            client.post(f"/packages/{package_id}/process")

    assert mock_graph.invoke.call_count == 2
    second_call_state = mock_graph.invoke.call_args_list[1][0][0]
    assert second_call_state["doc_type_overrides"] == {"claim.pdf": "cms1500"}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_reclassify_document tests/test_api.py::test_reclassify_document_404_for_wrong_package tests/test_api.py::test_reprocess_passes_overrides_to_graph -v`
Expected: FAIL — 404s (the reclassify route doesn't exist) and the third test fails on the `doc_type_overrides` assertion (process doesn't pass any).

- [ ] **Step 7: Add the reclassify endpoint and wire `process_package`**

In `api/main.py`, add a helper and update `_run_claim`'s signature (find the existing `def _run_claim(graph, package_id: str, pkg_dir: Path) -> None:` and its one `state = {...}` line):

```python
def _run_claim(graph, package_id: str, pkg_dir: Path, doc_type_overrides: dict[str, str] | None = None) -> None:
    session = db.SessionLocal()
    try:
        db.update_package_status(session, package_id, "processing")
        db.log_audit(session, package_id, "api", "extract")

        thread_id = str(uuid.uuid4())
        state = {"package_dir": str(pkg_dir), "domain": None, "doc_type_overrides": doc_type_overrides or {}}
```

(Only the function signature's new `doc_type_overrides` parameter and the `state = {...}` line change — the rest of `_run_claim`'s body is unchanged.)

Update `create_package`'s call site (`background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir)`) — no change needed, since `doc_type_overrides` defaults to `None` and a fresh upload has no prior `Document` rows to override.

Replace `process_package`'s body to look up overrides before scheduling:

```python
@app.post("/packages/{package_id}/process")
async def process_package(package_id: str, background_tasks: BackgroundTasks):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise HTTPException(status_code=404, detail="Package not found")
        overrides = {
            Path(doc.path).name: doc.doc_type
            for doc in db.list_documents(session, package_id)
            if doc.manually_overridden
        }
    finally:
        session.close()

    pkg_dir = Path(settings.storage_dir) / package_id
    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir, overrides)
    return {"package_id": package_id, "status": "queued"}
```

Add the new endpoint, right after `get_package_document`:

```python
@app.post("/packages/{package_id}/documents/{document_id}/reclassify")
async def reclassify_document(package_id: str, document_id: str, body: dict):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise HTTPException(status_code=404, detail="Document not found")

        doc.doc_type = body["doc_type"]
        doc.classification_reason = "manual override"
        doc.manually_overridden = True
        session.commit()

        db.log_audit(
            session, package_id, body.get("reviewer", "reviewer"), "reclassify",
            {"document_id": document_id, "doc_type": doc.doc_type},
        )
        return {
            "document_id": doc.id, "doc_type": doc.doc_type,
            "classification_reason": doc.classification_reason, "manually_overridden": doc.manually_overridden,
        }
    finally:
        session.close()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add src/claimflow/db.py api/main.py tests/test_db.py tests/test_api.py
git commit -m "feat: add document reclassify endpoint, wire overrides into reprocessing"
```

---

## Task 4: Surface classification metadata in the documents endpoints; README

**Files:**
- Modify: `api/main.py`
- Modify: `README.md`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `Document.classification_reason`, `Document.manually_overridden` (Task 3).
- Produces: nothing new for later tasks — this is the last task in the plan.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api.py`:

```python
def test_list_documents_includes_classification_metadata():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [{"path": "/tmp/claim.pdf", "doc_type": "cms1500", "has_text_layer": True,
                        "scan_quality": None, "classification_reason": "matched domain keyword 'cms-1500' for cms1500"}],
        "extraction_fields": [], "extraction_status": "pass", "extraction_overall_confidence": 0.9,
        "validation_failures": [], "policy_answers": [], "decision": "approved", "review_reasons": [], "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            package_id = response.json()["package_id"]

            docs = client.get(f"/packages/{package_id}/documents").json()

    assert docs[0]["classification_reason"] == "matched domain keyword 'cms-1500' for cms1500"
    assert docs[0]["manually_overridden"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_list_documents_includes_classification_metadata -v`
Expected: FAIL — `KeyError: 'classification_reason'` (the response dict doesn't include it yet).

- [ ] **Step 3: Update the documents endpoints' response shape**

In `api/main.py`, update `list_package_documents` and `get_package_document` to include the two new fields in their returned dicts:

```python
@app.get("/packages/{package_id}/documents")
async def list_package_documents(package_id: str):
    session = db.SessionLocal()
    try:
        return [
            {
                "document_id": doc.id, "path": doc.path, "doc_type": doc.doc_type,
                "has_text_layer": doc.has_text_layer, "scan_quality": doc.scan_quality,
                "classification_reason": doc.classification_reason, "manually_overridden": doc.manually_overridden,
            }
            for doc in db.list_documents(session, package_id)
        ]
    finally:
        session.close()


@app.get("/packages/{package_id}/documents/{document_id}")
async def get_package_document(package_id: str, document_id: str):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "document_id": doc.id, "path": doc.path, "doc_type": doc.doc_type,
            "has_text_layer": doc.has_text_layer, "scan_quality": doc.scan_quality,
            "classification_reason": doc.classification_reason, "manually_overridden": doc.manually_overridden,
        }
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: All pass.

- [ ] **Step 6: Update the README**

In `README.md`, under the `### Documents and evidence` block (added by the API-expansion plan), add a line for the new endpoint:

```
GET  /packages/{package_id}/documents                                     List documents in a package (includes doc_type, classification_reason, manually_overridden)
GET  /packages/{package_id}/documents/{document_id}                        One document's detail
GET  /packages/{package_id}/documents/{document_id}/pages/{page}           PNG render of one page (optional ?bbox=x0,y0,x1,y1 to highlight evidence)
POST /packages/{package_id}/documents/{document_id}/reclassify              Override a document's classified type; call POST .../process afterward to reprocess with it
GET  /packages/{package_id}/fields/{field_id}/evidence                     Source evidence for one extracted field
```

(Replace the existing 4-line block with this 5-line version — only the `documents` list line's description and the new `reclassify` line change; the other three lines are unchanged.)

Also update the "Document classification" section (search for `## Document classification` in `README.md`) — after its existing table, add:

```markdown
Classification is deterministic keyword matching, so every result carries a **reason** (which keyword matched, and for which type) — surfaced via `GET /packages/{package_id}/documents`. A reviewer can override a misclassified document with `POST /packages/{package_id}/documents/{document_id}/reclassify`, then `POST /packages/{package_id}/process` to reprocess it — the new type's schema and validators run on the next pass, and the package's detected domain is re-derived from the overridden classification.
```

- [ ] **Step 7: Commit**

```bash
git add api/main.py README.md tests/test_api.py
git commit -m "feat: surface classification reason and override status in documents API"
```

---

## Self-Review Notes

- **Spec coverage:** item 7 of the parent spec ("Document classification needs an override path") is addressed — detected type, classification reason, manual override, and reprocess action are all present as API primitives. "Optional confidence/strength indicator" is not implemented — classification here is deterministic keyword matching (yes/no match), not a scored/probabilistic classifier, so there is no meaningful confidence number to surface; the *reason string* (which keyword matched) is the strength/traceability signal this plan provides instead, matching the spec's explicit note that an LLM classifier is not required now.
- **Not in this plan:** the UI display of detected type/reason/override/reprocess (explicitly out of scope, per the user's standing instruction not to build UI yet).
- **Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.
