from pathlib import Path

import fitz  # PyMuPDF

import claimflow.domains  # noqa: F401 — triggers domain register() calls
from claimflow.domains.base import all_domains
from claimflow.state import ClaimState, IngestedDoc

_TEXT_THRESHOLD = 50


def _classify_doc_type(text: str) -> str:
    lower = text.lower()
    for domain in all_domains():
        if any(kw in lower for kw in domain.keywords):
            return domain.doc_type
    return "supporting"


def ingest_node(state: ClaimState) -> dict:
    pkg = Path(state["package_dir"])
    pdfs = sorted(pkg.glob("*.pdf"))
    if not pdfs:
        return {"error": f"No PDFs found in {pkg}", "documents": [], "domain": None}

    docs: list[IngestedDoc] = []
    detected_domain: str | None = None
    for pdf_path in pdfs:
        try:
            doc = fitz.open(str(pdf_path))
            first_page_text = next(iter(doc)).get_text() if len(doc) > 0 else ""
            has_text = len(first_page_text.strip()) >= _TEXT_THRESHOLD
            doc_type = _classify_doc_type(first_page_text)
            if doc_type != "supporting" and detected_domain is None:
                detected_domain = doc_type
            docs.append(IngestedDoc(path=str(pdf_path), doc_type=doc_type, has_text_layer=has_text))
        except Exception:
            docs.append(IngestedDoc(path=str(pdf_path), doc_type="unknown", has_text_layer=False))

    return {"documents": docs, "domain": detected_domain}
