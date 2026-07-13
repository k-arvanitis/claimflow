# Upload + Storage Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /packages` currently accepts any file, any size, any count, with no rollback on failure, and the API leaks full server-side filesystem paths in `GET .../documents` responses. Close these without touching local-filesystem storage itself (already an accepted portfolio-scope limitation) or the DOCX conversion path (it already has `timeout=60` — confirmed by inventory, not a gap).

**Architecture:** `create_package` validates BEFORE writing anything to disk (file count, extension allowlist) so an invalid request never touches the filesystem or the DB. During the actual write, a running byte-count per file enforces a max size; any violation (or any other write failure) triggers a full `shutil.rmtree` of the just-created package directory and the request fails before `db.create_package` ever runs — so a failed upload never leaves an orphaned DB row or orphaned files. Filenames within one upload that collide after sanitization get a short disambiguating suffix instead of silently overwriting each other. `DocumentSummary.path` (a raw server filesystem path, currently returned to clients) is replaced with `filename` (matches what `get_field_evidence` already correctly does via `Path(doc.path).name`). `get_document_page_image` gains a containment check — the resolved `doc.path` must sit inside that package's own directory before `render_page` ever opens it, a defense-in-depth check independent of whether `doc.path` could realistically go wrong today.

**Tech Stack:** FastAPI, Python stdlib (`pathlib`, `shutil`), pytest. No new dependencies.

## Global Constraints

- `_INGESTIBLE_SUFFIXES` in `src/claimflow/nodes/ingest.py` (currently `{".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp", ".docx"}`) becomes the single source of truth for allowed upload extensions — rename it to the public `INGESTIBLE_SUFFIXES` (drop the leading underscore, it's now imported cross-module) rather than duplicating the set in `api/main.py`.
- New `Settings` fields: `max_upload_size_bytes: int = 20_000_000` (20MB per file), `max_files_per_package: int = 30`. Both overridable via env var like every other `Settings` field.
- A rejected upload (bad extension, too many files, oversized file, or any disk-write error) leaves **zero** trace: no package directory, no `Package` row, no partial files. Validate count/extensions before any disk write; on a size/write failure mid-copy, `rmtree` the whole package directory before raising.
- Filename collisions within a single upload (two files with the same name after sanitization) get a short disambiguating suffix (e.g. `claim_1.pdf`, `claim_2.pdf`) — never silently overwrite one another.
- `DocumentSummary.filename` replaces `DocumentSummary.path` — no route ever returns a full server filesystem path to a client again. (`get_field_evidence`'s `filename` field, added in an earlier plan, is the existing precedent for this.)
- `get_document_page_image` verifies `Path(doc.path).resolve()` is inside `(Path(settings.storage_dir) / package_id).resolve()` before calling `render_page` — a 404 (not a 500) on failure, consistent with the route's existing `DOCUMENT_NOT_FOUND` pattern.
- No changes to DOCX conversion (`_office_to_pdf` in `ingest.py`) — it already has a 60s timeout, confirmed by inventory; not a gap this plan needs to close.
- No changes to `delete_package`'s existing `shutil.rmtree(pkg_dir, ignore_errors=True)` cleanup — it already runs on every package deletion; this plan doesn't touch it.

---

### Task 1: Upload validation, size/count limits, atomic rollback, collision-safe naming

**Files:**
- Modify: `src/claimflow/nodes/ingest.py` (rename `_INGESTIBLE_SUFFIXES` → `INGESTIBLE_SUFFIXES`)
- Modify: `src/claimflow/config.py` (`max_upload_size_bytes`, `max_files_per_package`)
- Modify: `api/main.py` (`create_package`)
- Test: `tests/test_upload_hardening.py`

**Interfaces:**
- Produces: `settings.max_upload_size_bytes`, `settings.max_files_per_package`, `INGESTIBLE_SUFFIXES` — consumed only by `create_package` in this plan.

- [ ] **Step 1: Write the failing test**

```python
import io

from fastapi.testclient import TestClient

from api.main import app


def test_upload_rejects_unsupported_extension():
    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[("files", ("malware.exe", io.BytesIO(b"x"), "application/octet-stream"))],
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_rejects_too_many_files(monkeypatch):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "max_files_per_package", 2)

    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[
                ("files", ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")),
                ("files", ("b.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")),
                ("files", ("c.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")),
            ],
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TOO_MANY_FILES"


def test_upload_rejects_oversized_file_and_leaves_no_trace(monkeypatch, tmp_path):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "max_upload_size_bytes", 10)
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[("files", ("big.pdf", io.BytesIO(b"%PDF-1.4" * 100), "application/pdf"))],
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert list(tmp_path.iterdir()) == []  # no orphaned package directory


def test_upload_rejects_no_files_leaves_no_trace_and_no_db_row(monkeypatch, tmp_path):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    from claimflow import db

    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[("files", ("bad.exe", io.BytesIO(b"x"), "application/octet-stream"))],
        )
    assert resp.status_code == 400
    assert list(tmp_path.iterdir()) == []

    session = db.SessionLocal()
    assert db.list_packages(session).__len__() == 0 if hasattr(db.list_packages(session), "__len__") else True
    session.close()


def test_upload_disambiguates_duplicate_filenames_in_same_upload(monkeypatch, tmp_path):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[
                ("files", ("claim.pdf", io.BytesIO(b"%PDF-1.4 first"), "application/pdf")),
                ("files", ("claim.pdf", io.BytesIO(b"%PDF-1.4 second"), "application/pdf")),
            ],
        )
    assert resp.status_code == 200
    package_id = resp.json()["package_id"]
    stored_files = sorted(p.name for p in (tmp_path / package_id).iterdir())
    assert len(stored_files) == 2  # both files present, neither overwrote the other
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upload_hardening.py -v`
Expected: FAIL — none of these checks exist yet; oversized/unsupported files are silently accepted, duplicate filenames overwrite each other.

- [ ] **Step 3: Rename `_INGESTIBLE_SUFFIXES` to `INGESTIBLE_SUFFIXES`**

In `src/claimflow/nodes/ingest.py`, rename every occurrence of `_INGESTIBLE_SUFFIXES` to `INGESTIBLE_SUFFIXES` (the definition and its one use in `ingest_node`, `ingest.py:61`).

- [ ] **Step 4: Add the two new `Settings` fields**

In `src/claimflow/config.py`, add near `storage_dir`:

```python
    max_upload_size_bytes: int = 20_000_000  # 20MB per file
    max_files_per_package: int = 30
```

- [ ] **Step 5: Rewrite `create_package`**

Replace `api/main.py:222-240`:

```python
async def create_package(files: list[UploadFile], background_tasks: BackgroundTasks):
    if len(files) > settings.max_files_per_package:
        raise AppError(400, "TOO_MANY_FILES", f"A package may contain at most {settings.max_files_per_package} files")

    for f in files:
        name = Path(f.filename or "").name
        if not name or Path(name).suffix.lower() not in INGESTIBLE_SUFFIXES:
            raise AppError(400, "UNSUPPORTED_FILE_TYPE", f"Unsupported file type: {f.filename!r}")

    package_id = str(uuid.uuid4())
    pkg_dir = Path(settings.storage_dir) / package_id
    pkg_dir.mkdir(parents=True, exist_ok=True)

    try:
        used_names: set[str] = set()
        for f in files:
            name = Path(f.filename).name
            if name in used_names:
                stem, suffix = Path(name).stem, Path(name).suffix
                n = 1
                while f"{stem}_{n}{suffix}" in used_names:
                    n += 1
                name = f"{stem}_{n}{suffix}"
            used_names.add(name)

            dest = pkg_dir / name
            written = 0
            with open(dest, "wb") as out:
                while chunk := f.file.read(1024 * 1024):
                    written += len(chunk)
                    if written > settings.max_upload_size_bytes:
                        raise AppError(
                            400, "FILE_TOO_LARGE",
                            f"{f.filename!r} exceeds the {settings.max_upload_size_bytes}-byte limit",
                        )
                    out.write(chunk)
    except Exception:
        shutil.rmtree(pkg_dir, ignore_errors=True)
        raise

    session = db.SessionLocal()
    try:
        db.create_package(session, package_id)
        db.log_audit(session, package_id, "api", "upload", {"filenames": list(used_names)})
        db.transition_package_status(session, package_id, "queued", reason="upload complete")
    except Exception:
        shutil.rmtree(pkg_dir, ignore_errors=True)
        raise
    finally:
        session.close()

    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir)
    return PackageCreateResponse(package_id=package_id, status=PackageStatus.QUEUED)
```

Add `from claimflow.nodes.ingest import INGESTIBLE_SUFFIXES` to `api/main.py`'s imports.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_upload_hardening.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Run the full suite to check for regressions**

Run: `uv run pytest tests/ -q`
Expected: same pass count as baseline plus 5 — every existing upload test uses a single well-formed `.pdf` file under the new limits, so none should break; if one does, read why before "fixing" it (a real regression here matters).

- [ ] **Step 8: Commit**

```bash
git add src/claimflow/nodes/ingest.py src/claimflow/config.py api/main.py tests/test_upload_hardening.py
git commit -m "feat: validate upload count/extension/size, atomic rollback, dedupe filenames"
```

---

### Task 2: Stop exposing raw filesystem paths

**Files:**
- Modify: `src/claimflow/schemas/documents.py` (`DocumentSummary`)
- Modify: `api/main.py` (`list_package_documents`, `get_package_document`)
- Test: `tests/test_upload_hardening.py`

**Interfaces:**
- Produces: `DocumentSummary.filename` — no other schema in this codebase currently exposes `path`, confirmed by inventory (only `DocumentSummary` did).

- [ ] **Step 1: Write the failing test**

```python
def test_document_list_does_not_expose_filesystem_path():
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("claim.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]
        resp = client.get(f"/packages/{package_id}/documents")

    body = resp.json()
    assert len(body) == 1
    assert "path" not in body[0]
    assert body[0]["filename"] == "claim.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upload_hardening.py -v -k filesystem_path`
Expected: FAIL — `DocumentSummary` still has `path`, not `filename`.

- [ ] **Step 3: Replace `path` with `filename` in `DocumentSummary`**

In `src/claimflow/schemas/documents.py`, replace:

```python
class DocumentSummary(BaseModel):
    document_id: str
    path: str
    doc_type: DocumentType
```

with:

```python
class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    doc_type: DocumentType
```

- [ ] **Step 4: Update the two construction sites in `api/main.py`**

Both `list_package_documents` and `get_package_document` build `DocumentSummary(document_id=doc.id, path=doc.path, doc_type=doc.doc_type, ...)` — in each, replace `path=doc.path` with `filename=Path(doc.path).name`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_upload_hardening.py tests/ -q`
Expected: PASS — full suite green (confirmed no existing test asserted on the `path` field's value, only `document_id`/`doc_type`).

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/schemas/documents.py api/main.py tests/test_upload_hardening.py
git commit -m "feat: stop exposing raw filesystem paths in document API responses"
```

---

### Task 3: Path-containment check on page rendering

**Files:**
- Modify: `api/main.py` (`get_document_page_image`)
- Test: `tests/test_upload_hardening.py`

**Interfaces:**
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

```python
def test_page_render_rejects_document_path_outside_package_dir(tmp_path, monkeypatch):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    from claimflow import db

    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("claim.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

    outside_file = tmp_path.parent / "outside.pdf"
    outside_file.write_bytes(b"%PDF-1.4 secret")

    session = db.SessionLocal()
    doc = db.Document(id="evil-doc", package_id=package_id, path=str(outside_file), doc_type="cms1500", has_text_layer=True)
    session.add(doc)
    session.commit()
    session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/{package_id}/documents/evil-doc/pages/1")

    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upload_hardening.py -v -k outside_package_dir`
Expected: FAIL — `render_page` is called with the out-of-package path and (depending on the file's content) may actually succeed in opening it.

- [ ] **Step 3: Add the containment check**

In `api/main.py`'s `get_document_page_image`, after the existing `doc is None or doc.package_id != package_id` check, add:

```python
    pkg_dir = Path(settings.storage_dir) / package_id
    try:
        resolved_doc_path = Path(doc.path).resolve()
        resolved_pkg_dir = pkg_dir.resolve()
    except OSError:
        raise AppError(404, "DOCUMENT_NOT_FOUND", "Document does not exist")
    if resolved_pkg_dir not in resolved_doc_path.parents and resolved_doc_path != resolved_pkg_dir:
        raise AppError(404, "DOCUMENT_NOT_FOUND", "Document does not exist")
```

(place this check inside the same `session = db.SessionLocal() / try / finally` block the existing `doc` lookup uses, right after the existing 404 check — read the current function body first to fit it in correctly rather than assuming exact surrounding line numbers)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_upload_hardening.py tests/ -q`
Expected: PASS — full suite green except the 3 pre-existing unrelated `tests/test_real_public_eval.py` failures.

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_upload_hardening.py
git commit -m "feat: reject page-render requests for documents outside their package directory"
```

---

## Self-Review Notes

- **Spec coverage:** filename sanitization (existing `.name` strip + Task 1's empty/unsupported-name rejection), path-traversal prevention (Task 3's containment check, defense-in-depth on top of the pre-existing `.name`-strip), MIME/extension checks (Task 1, extension only — content-type sniffing beyond extension isn't attempted, matching the existing ingest pipeline's own extension-based dispatch), max file size (Task 1), max package file count (Task 1), unique internal storage names (Task 1's collision disambiguation), cleanup after package deletion (already existed, unchanged, confirmed by inventory), no raw filesystem paths exposed (Task 2), failed uploads leave no orphaned records/files (Task 1's rollback), safe DOCX conversion timeouts (already existed — `timeout=60`, confirmed by inventory, no change needed), rendered pages can't access documents outside their package (Task 3), temporary files cleaned (the only temp artifact, `.converted/`, already gets removed via full package deletion — no separate mechanism needed since nothing else in the codebase uses `tempfile`, confirmed by inventory).
- **Placeholder scan:** none found.
- **Type consistency:** `DocumentSummary.filename` (Task 2) doesn't collide with `FieldEvidenceResponse.filename` (added in an earlier plan) — same name, same meaning (`Path(doc.path).name`), consistent convention across the API surface.
