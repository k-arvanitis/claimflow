import subprocess
from pathlib import Path

from doc_intel.artifact import build_artifact

import claimflow.domains  # noqa: F401 — triggers domain register() calls
from claimflow.domains.base import all_domains
from claimflow.state import ClaimState, IngestedDoc

_TEXT_THRESHOLD = 50
_OCR_LOW_CONF_THRESHOLD = 20  # chars; below this, OCR likely failed on a low-quality scan

# fitz opens PDFs and raster images natively (an image becomes a 1-page pseudo-PDF).
# DOCX has no such native support, so it's converted to PDF first — after that every
# input goes through the exact same page-based pipeline (classification, OCR, bbox evidence).
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"}
_OFFICE_SUFFIXES = {".docx"}
_INGESTIBLE_SUFFIXES = {".pdf"} | _IMAGE_SUFFIXES | _OFFICE_SUFFIXES


def _office_to_pdf(path: Path, out_dir: Path) -> Path:
    """Convert a DOCX to PDF via headless LibreOffice."""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(path)],
        check=True, capture_output=True, timeout=60,
    )
    pdf_path = out_dir / f"{path.stem}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"LibreOffice did not produce {pdf_path}")
    return pdf_path


def _scan_quality(text: str) -> float:
    """Heuristic OCR quality proxy: extracted character count relative to a normal
    text page, capped at 1.0. Not a real per-word confidence score (fitz's tesseract
    wrapper doesn't expose one) — a density signal to flag likely-failed scans."""
    return min(len(text.strip()) / (_TEXT_THRESHOLD * 4), 1.0)


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

            doc_type, classification_reason = _classify_doc_type(first_page_text)
            if doc_type in domain_keys and detected_domain is None:
                detected_domain = doc_type
            docs.append(IngestedDoc(
                path=str(pdf_path), doc_type=doc_type,
                has_text_layer=has_text, scan_quality=scan_quality,
                classification_reason=classification_reason,
            ))
        except Exception:
            ocr_log.append(f"{name}: ingest failed, marked unknown")
            docs.append(IngestedDoc(
                path=str(src_path), doc_type="unknown", has_text_layer=False, scan_quality=None,
                classification_reason=None,
            ))

    return {"documents": docs, "domain": detected_domain, "ocr_log": ocr_log}
