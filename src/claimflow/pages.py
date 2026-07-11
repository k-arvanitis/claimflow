"""Shared PDF page rendering — used by both the Streamlit review UI and the API's
page-image endpoint, so there's one fitz-rendering implementation, not two."""
import fitz  # PyMuPDF


def render_page(pdf_path: str, page_no: int, bbox: list[float] | None = None) -> bytes | None:
    """Render a PDF page as PNG bytes, drawing a red box around the evidence if bbox is known."""
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_no - 1]
        if bbox:
            page.draw_rect(fitz.Rect(bbox), color=(1, 0, 0), width=2)
        pix = page.get_pixmap(dpi=150)
        return pix.tobytes("png")
    except Exception:
        return None
