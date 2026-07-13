# Ingest/DocIntel OCR Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop maintaining a second, ClaimFlow-owned OCR implementation (`fitz`/tesseract calls in `ingest.py`) and delegate all PDF parsing, native-text detection, and OCR routing to `doc-intel`'s `build_artifact()`. ClaimFlow keeps its own concerns — domain/doc_type classification, package assembly — untouched.

**Architecture:** `ingest_node` currently opens each PDF with `fitz`, checks page-1 text length itself, and falls back to its own `page.get_textpage_ocr()` call when the page looks scanned. Replace that block with a single `build_artifact(pdf_path)` call from the local `doc-intel` dependency (`~/doc-intel`, already a path dependency in `pyproject.toml`), and read `has_text_layer` / OCR-triggered / page-1 text off the returned `DocumentArtifact.pages[0]` instead. `_classify_doc_type` (ClaimFlow's own claim-domain classifier — separate from doc-intel's generic invoice/cv/contract classifier) keeps running on that same page text, unchanged. The `IngestedDoc` contract (`has_text_layer`, `scan_quality`) and the `ocr_log` message format are preserved exactly, since Streamlit and the API response already depend on them.

**Tech Stack:** `doc-intel` (local path dependency, already installed), no new dependencies. Removes the direct `fitz`/tesseract OCR call path from `claimflow` — `fitz` import is dropped entirely from `ingest.py` once nothing there calls it directly.

## Global Constraints

- Do not touch `doc-intel` itself (`~/doc-intel`) — this plan only changes how ClaimFlow *calls* it.
- Do not change `_classify_doc_type`'s logic or `all_domains()`/domain registration — ClaimFlow's own claim-domain classification is explicitly out of scope (doc-intel's own `classify()` is a *different*, generic doc-type classifier — invoice/cv/contract/report — not a substitute).
- `IngestedDoc`'s fields (`path`, `doc_type`, `has_text_layer`, `scan_quality`) in `src/claimflow/state.py` do not change shape — Streamlit and the API response read them as-is.
- `ocr_log` message strings keep their existing format (`"{name}: page 1 has no text layer — falling back to OCR"`, `"{name}: OCR yielded very little text (...) — possible low-quality scan"`, `"{name}: converted to PDF for processing"`, `"{name}: ingest failed, marked unknown"`) — Streamlit/API consumers match on these being human-readable log lines, not on exact text, but keep them recognizable and don't remove the low-quality-scan warning.
- `_office_to_pdf` (DOCX → PDF via LibreOffice) is unchanged — it's a format-conversion step, not OCR, and out of scope for this plan.
- Known, accepted behavior change: doc-intel's own native-text-layer threshold (`_TEXT_LAYER_MIN = 10` chars) differs from ClaimFlow's old `_TEXT_THRESHOLD = 50`. This plan accepts doc-intel's threshold as authoritative — OCR routing is now doc-intel's job, not ClaimFlow's — and does not attempt to preserve the old 50-char cutoff.
- `_scan_quality()`'s density-heuristic formula (`min(len(text.strip()) / (_TEXT_THRESHOLD * 4), 1.0)`) is preserved as-is; it's applied to text now sourced from doc-intel's artifact instead of ClaimFlow's own OCR call, but the formula and its meaning (a density proxy, not real OCR confidence) don't change.

---

## File Structure

- **Modify: `src/claimflow/nodes/ingest.py`** — replace the `fitz`-based text-layer/OCR block in `ingest_node` with `build_artifact()`; delete `ocr_page()` (dead once nothing calls it) and drop the `import fitz` line.
- **Modify: `tests/test_graph.py`** — the two tests that `patch("claimflow.nodes.ingest.fitz.open", ...)` (`test_ingest_node_classifies_cms1500`, `test_graph_runs_end_to_end`) must instead mock `claimflow.nodes.ingest.build_artifact`.
- **Modify: `README.md`** — reword the OCR-proof and supported-inputs sections so they describe OCR as a doc-intel capability ClaimFlow depends on, not something ClaimFlow implements directly.

---

## Task 1: Replace the fitz/OCR block in `ingest_node` with `build_artifact()`

**Files:**
- Modify: `src/claimflow/nodes/ingest.py`
- Test: `tests/test_graph.py` (existing tests in this file exercise `ingest_node`; Task 2 updates the two that mock `fitz` directly — this task's own verification step runs the full file so you'll see which currently-passing tests break and need the Task 2 update next)

**Interfaces:**
- Consumes: `build_artifact(source: str) -> DocumentArtifact` from `doc_intel.artifact` (already an installed dependency — importable as `from doc_intel.artifact import build_artifact`). `DocumentArtifact.pages` is a `list[PageArtifact]`; each `PageArtifact` has `.text: str`, `.native_text_available: bool`, `.ocr_used: bool`, and `.quality` (not needed directly here — page-level `.text`/`.native_text_available`/`.ocr_used` are sufficient).
- Produces: `ingest_node(state) -> dict` keeps its existing return shape (`{"documents": [...], "domain": ..., "ocr_log": [...]}`, or `{"error": ..., "documents": [], "domain": None}`) — consumed by `graph.py`'s `extract_node` and by `api/main.py`'s response building, both unchanged by this plan.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_graph.py`, right after the existing imports at the top of the file:

```python
def test_ingest_node_uses_build_artifact(tmp_path):
    """Ingest node delegates OCR/text-layer detection to doc-intel's build_artifact,
    not its own fitz call."""
    from unittest.mock import MagicMock, patch

    pkg = tmp_path / "package"
    pkg.mkdir()
    claim_pdf = pkg / "claim.pdf"
    claim_pdf.write_bytes(b"placeholder")

    fake_page = MagicMock()
    fake_page.text = "HEALTH INSURANCE CLAIM FORM CMS-1500\nBox 1a: INS123"
    fake_page.native_text_available = True
    fake_page.ocr_used = False
    fake_artifact = MagicMock()
    fake_artifact.pages = [fake_page]

    with patch("claimflow.nodes.ingest.build_artifact", return_value=fake_artifact) as mock_build:
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
        }
        result = ingest_node(state)

    assert mock_build.called
    docs = result["documents"]
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "cms1500"
    assert docs[0]["has_text_layer"] is True
    assert docs[0]["scan_quality"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py::test_ingest_node_uses_build_artifact -v`
Expected: FAIL with `AttributeError: <module 'claimflow.nodes.ingest' ...> does not have the attribute 'build_artifact'` (nothing to patch yet).

- [ ] **Step 3: Rewrite `ingest.py`**

In `src/claimflow/nodes/ingest.py`:

Replace the import block at the top:

```python
import subprocess
from pathlib import Path

import fitz  # PyMuPDF

import claimflow.domains  # noqa: F401 — triggers domain register() calls
from claimflow.domains.base import all_domains
from claimflow.state import ClaimState, IngestedDoc
```

with:

```python
import subprocess
from pathlib import Path

from doc_intel.artifact import build_artifact

import claimflow.domains  # noqa: F401 — triggers domain register() calls
from claimflow.domains.base import all_domains
from claimflow.state import ClaimState, IngestedDoc
```

Delete the `ocr_page()` function entirely (it's replaced by `build_artifact`'s own OCR routing):

```python
def ocr_page(doc: fitz.Document, page_index: int) -> str:
    """Run tesseract OCR on one page of a scanned PDF via fitz's built-in OCR."""
    if page_index >= len(doc):
        return ""
    try:
        page = doc[page_index]
        tp = page.get_textpage_ocr(dpi=300, full=False)
        return page.get_text(textpage=tp)
    except Exception:
        return ""
```

Keep `_scan_quality()` exactly as-is (it's a pure text-density function, doesn't touch `fitz`):

```python
def _scan_quality(text: str) -> float:
    """Heuristic OCR quality proxy: extracted character count relative to a normal
    text page, capped at 1.0. Not a real per-word confidence score (fitz's tesseract
    wrapper doesn't expose one) — a density signal to flag likely-failed scans."""
    return min(len(text.strip()) / (_TEXT_THRESHOLD * 4), 1.0)
```

Keep `_classify_doc_type()` unchanged.

Replace the body of the `for src_path in sources:` loop in `ingest_node` (currently the block from `doc = fitz.open(str(pdf_path))` through the `docs.append(IngestedDoc(...))` inside the `try`) with:

```python
            artifact = build_artifact(str(pdf_path))
            page1 = artifact.pages[0] if artifact.pages else None
            first_page_text = page1.text if page1 else ""
            has_text = bool(page1 and page1.native_text_available)
            scan_quality: float | None = None

            if page1 and page1.ocr_used:
                ocr_log.append(f"{name}: page 1 has no text layer — falling back to OCR")
                scan_quality = _scan_quality(first_page_text)
                if len(first_page_text.strip()) < _OCR_LOW_CONF_THRESHOLD:
                    ocr_log.append(
                        f"{name}: OCR yielded very little text ({len(first_page_text.strip())} chars) "
                        "— possible low-quality scan"
                    )

            doc_type = _classify_doc_type(first_page_text)
            if doc_type in domain_keys and detected_domain is None:
                detected_domain = doc_type
            docs.append(IngestedDoc(
                path=str(pdf_path), doc_type=doc_type,
                has_text_layer=has_text, scan_quality=scan_quality,
            ))
```

The full `ingest_node` function should now read:

```python
def ingest_node(state: ClaimState) -> dict:
    pkg = Path(state["package_dir"])
    sources = sorted(p for p in pkg.iterdir() if p.suffix.lower() in _INGESTIBLE_SUFFIXES)
    if not sources:
        return {"error": f"No supported documents found in {pkg}", "documents": [], "domain": None}

    domain_keys = {d.doc_type for d in all_domains()}
    docs: list[IngestedDoc] = []
    ocr_log: list[str] = []
    detected_domain: str | None = None
    convert_dir = pkg / ".converted"
    for src_path in sources:
        name = src_path.name
        try:
            if src_path.suffix.lower() in _OFFICE_SUFFIXES:
                pdf_path = _office_to_pdf(src_path, convert_dir)
                ocr_log.append(f"{name}: converted to PDF for processing")
            else:
                pdf_path = src_path

            artifact = build_artifact(str(pdf_path))
            page1 = artifact.pages[0] if artifact.pages else None
            first_page_text = page1.text if page1 else ""
            has_text = bool(page1 and page1.native_text_available)
            scan_quality: float | None = None

            if page1 and page1.ocr_used:
                ocr_log.append(f"{name}: page 1 has no text layer — falling back to OCR")
                scan_quality = _scan_quality(first_page_text)
                if len(first_page_text.strip()) < _OCR_LOW_CONF_THRESHOLD:
                    ocr_log.append(
                        f"{name}: OCR yielded very little text ({len(first_page_text.strip())} chars) "
                        "— possible low-quality scan"
                    )

            doc_type = _classify_doc_type(first_page_text)
            if doc_type in domain_keys and detected_domain is None:
                detected_domain = doc_type
            docs.append(IngestedDoc(
                path=str(pdf_path), doc_type=doc_type,
                has_text_layer=has_text, scan_quality=scan_quality,
            ))
        except Exception:
            ocr_log.append(f"{name}: ingest failed, marked unknown")
            docs.append(IngestedDoc(path=str(src_path), doc_type="unknown", has_text_layer=False, scan_quality=None))

    return {"documents": docs, "domain": detected_domain, "ocr_log": ocr_log}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py::test_ingest_node_uses_build_artifact -v`
Expected: PASS

- [ ] **Step 5: Run the whole test file to see what else broke**

Run: `uv run pytest tests/test_graph.py -v`
Expected: `test_ingest_node_classifies_cms1500` and `test_graph_runs_end_to_end` FAIL (they patch `claimflow.nodes.ingest.fitz.open`, which no longer exists since `fitz` isn't imported in this module anymore) — `test_ingest_node_handles_docx_and_image` should still PASS (it doesn't mock fitz; it exercises `_office_to_pdf` + `build_artifact` for real, against real docx/image fixtures it creates on disk). This is expected — Task 2 fixes the two broken tests.

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/nodes/ingest.py tests/test_graph.py
git commit -m "feat: delegate OCR and text-layer detection to doc-intel's build_artifact"
```

---

## Task 2: Update the two tests that mock `fitz` directly

**Files:**
- Modify: `tests/test_graph.py`

**Interfaces:**
- Consumes: `claimflow.nodes.ingest.build_artifact` (now the function to patch, per Task 1).
- Produces: nothing new for later tasks — this task only fixes test mocking to match Task 1's implementation change.

- [ ] **Step 1: Write the failing test (already failing from Task 1 — confirm the exact failure first)**

Run: `uv run pytest tests/test_graph.py::test_ingest_node_classifies_cms1500 tests/test_graph.py::test_graph_runs_end_to_end -v`
Expected: Both FAIL with `AttributeError: <module 'claimflow.nodes.ingest' ...> does not have the attribute 'fitz'`.

- [ ] **Step 2: Rewrite `test_ingest_node_classifies_cms1500`**

Replace the test's body (from the `def mock_open(path):` line through the `with patch(...)` line) with a `build_artifact` mock. The full replacement test:

```python
def test_ingest_node_classifies_cms1500(tmp_path):
    """Ingest node identifies the claim form and supporting docs."""
    from unittest.mock import MagicMock, patch

    pkg = tmp_path / "package"
    pkg.mkdir()
    claim_pdf = pkg / "claim.pdf"
    other_pdf = pkg / "discharge.pdf"
    claim_pdf.write_bytes(b"placeholder")
    other_pdf.write_bytes(b"placeholder")

    def mock_build_artifact(path):
        page = MagicMock()
        page.native_text_available = True
        page.ocr_used = False
        if "claim" in str(path):
            page.text = "HEALTH INSURANCE CLAIM FORM CMS-1500\nBox 1a: INS123"
        else:
            page.text = "DISCHARGE SUMMARY\nPatient: John Doe\nDischarge diagnosis and instructions follow below in full detail."  # noqa: E501
        artifact = MagicMock()
        artifact.pages = [page]
        return artifact

    with patch("claimflow.nodes.ingest.build_artifact", side_effect=mock_build_artifact):
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
        }
        result = ingest_node(state)

    docs = result["documents"]
    assert len(docs) == 2
    claim_doc = next(d for d in docs if d["doc_type"] == "cms1500")
    assert claim_doc["has_text_layer"] is True

    other_doc = next(d for d in docs if d["path"] != claim_doc["path"])
    assert other_doc["doc_type"] == "discharge_summary"
```

- [ ] **Step 3: Rewrite `test_graph_runs_end_to_end`**

In the same file, replace the `mock_fitz_open` function and the `with patch(...)` block:

```python
def test_graph_runs_end_to_end(tmp_path):
    """Graph executes all nodes and produces a decision."""
    from unittest.mock import MagicMock, patch

    claim_pdf = tmp_path / "claim.pdf"
    claim_pdf.write_bytes(b"placeholder")

    def mock_build_artifact(path):
        page = MagicMock()
        page.text = "HEALTH INSURANCE CLAIM FORM CMS-1500\nBox 1a: INS123"
        page.native_text_available = True
        page.ocr_used = False
        artifact = MagicMock()
        artifact.pages = [page]
        return artifact

    fake_extraction = MagicMock()
    fake_extraction.data = {
        "insurance_id": "INS123", "patient_name": "DOE JOHN",
        "patient_dob": "01011980", "billing_provider_npi": "1487293650",
        "diagnosis_codes": ["J06.9"],
        "service_lines": [{"cpt_code": "99213", "date_of_service": "01012026", "charges": "150.00", "units": 1, "place_of_service": "11", "diagnosis_pointer": "A"}],  # noqa: E501
        "total_charge": "150.00", "signature_on_file": True,
    }
    fake_extraction.fields = []
    fake_extraction.overall_confidence = 0.88
    fake_extraction.status = "pass"

    with patch("claimflow.nodes.ingest.build_artifact", side_effect=mock_build_artifact), \
         patch("claimflow.nodes.extract.extract", return_value=fake_extraction), \
         patch("claimflow.lookups.icd10.is_valid_icd10", return_value=True), \
         patch("claimflow.lookups.cpt.is_valid_cpt", return_value=True):
        from claimflow.graph import build_graph
        app = build_graph()
        result = app.invoke({"package_dir": str(tmp_path)}, config={"configurable": {"thread_id": "test"}})

    assert result["decision"] in ("approved", "flagged", "escalated")
    assert result["documents"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py -v`
Expected: All tests in the file PASS, including `test_ingest_node_handles_docx_and_image` (untouched, still exercises the real path) and `test_ingest_node_uses_build_artifact` from Task 1.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: All tests pass, no regressions elsewhere.

- [ ] **Step 6: Commit**

```bash
git add tests/test_graph.py
git commit -m "test: mock build_artifact instead of fitz.open in graph tests"
```

---

## Task 3: Update README wording for OCR ownership

**Files:**
- Modify: `README.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: No test** (documentation-only change, matches this repo's own convention of doc-only edits without a test step — see the earlier README wording fixes in this same session, items 2/5/6 of the parent spec, which were doc-only edits with no test step).

- [ ] **Step 2: Edit the four locations**

In `README.md`, line 11, replace:

```
**Supported inputs:** born-digital PDFs, scanned/image-only PDFs (OCR fallback via tesseract), standalone images (PNG/JPG/WEBP/TIFF/BMP), DOCX (converted to PDF via LibreOffice so it goes through the same page-based pipeline as everything else), and multi-document packages mixing any of these.
```

with:

```
**Supported inputs:** born-digital PDFs, scanned/image-only PDFs (OCR fallback via [doc-intel](../doc-intel), tesseract by default), standalone images (PNG/JPG/WEBP/TIFF/BMP), DOCX (converted to PDF via LibreOffice so it goes through the same page-based pipeline as everything else), and multi-document packages mixing any of these.
```

Line 31 (pipeline table), replace:

```
| Ingest | Deterministic | Reads PDFs, images, and DOCX from the package directory; OCR fallback via tesseract; classifies every document by type |
```

with:

```
| Ingest | Deterministic | Reads PDFs, images, and DOCX from the package directory; text-layer detection and OCR fallback via [doc-intel](../doc-intel)'s `build_artifact()`; classifies every document by type |
```

Line 83 (OCR proof section), replace:

```
- **Low-quality scan detection** — a density heuristic (extracted characters vs. a normal text page) flags likely-failed scans. It is not a real per-word OCR confidence score — PyMuPDF's tesseract wrapper doesn't expose one — so it's surfaced as a detection signal, not a confidence metric.
```

with:

```
- **Low-quality scan detection** — a density heuristic (extracted characters vs. a normal text page) flags likely-failed scans. It is not a real per-word OCR confidence score — doc-intel's OCR backends don't expose one — so it's surfaced as a detection signal, not a confidence metric.
```

Line 310 (Known limitations), replace:

```
- **Scan quality is a heuristic, not real OCR confidence** — a character-density proxy; PyMuPDF's tesseract wrapper doesn't expose true per-word confidence (see [OCR proof](#ocr-proof)).
```

with:

```
- **Scan quality is a heuristic, not real OCR confidence** — a character-density proxy computed by ClaimFlow over the text doc-intel returns; doc-intel's OCR backends don't expose true per-word confidence (see [OCR proof](#ocr-proof)).
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: attribute OCR/text-layer detection to doc-intel, not ClaimFlow directly"
```

---

## Self-Review Notes

- **Spec coverage:** item 1 of the parent spec ("avoid maintaining two OCR implementations") is fully addressed — `ingest.py` no longer imports `fitz` or calls `page.get_textpage_ocr()`; all OCR routing goes through `doc_intel.artifact.build_artifact()`. ClaimFlow's own classification logic (`_classify_doc_type`, domain registration) is explicitly preserved, per the parent spec's note that doc-intel's classifier is a different, generic concern.
- **Not in this plan:** doc-intel's own OCR backend choice (tesseract/LightOn/PaddleOCR/Surya) is doc-intel's config, not touched here. The DOCX→PDF conversion step (`_office_to_pdf`) is untouched — it's format conversion, not OCR, and out of scope.
- **Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.
