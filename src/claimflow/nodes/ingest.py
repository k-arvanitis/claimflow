from pathlib import Path

import fitz  # PyMuPDF

from claimflow.state import ClaimState, IngestedDoc

_TEXT_THRESHOLD = 50
_CLAIM_KEYWORDS = {"cms-1500", "health insurance claim form", "cms 1500"}


def _classify_doc_type(text: str) -> str:
    lower = text.lower()
    if any(kw in lower for kw in _CLAIM_KEYWORDS):
        return "cms1500"
    return "supporting"


def ingest_node(state: ClaimState) -> dict:
    pkg = Path(state["package_dir"])
    pdfs = sorted(pkg.glob("*.pdf"))
    if not pdfs:
        return {"error": f"No PDFs found in {pkg}", "documents": []}

    docs: list[IngestedDoc] = []
    for pdf_path in pdfs:
        try:
            doc = fitz.open(str(pdf_path))
            first_page_text = next(iter(doc)).get_text() if len(doc) > 0 else ""
            has_text = len(first_page_text.strip()) >= _TEXT_THRESHOLD
            doc_type = _classify_doc_type(first_page_text)
            docs.append(IngestedDoc(
                path=str(pdf_path),
                doc_type=doc_type,
                has_text_layer=has_text,
            ))
        except Exception:
            docs.append(IngestedDoc(
                path=str(pdf_path),
                doc_type="unknown",
                has_text_layer=False,
            ))

    return {"documents": docs}
