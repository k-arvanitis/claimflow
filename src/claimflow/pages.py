"""Shared PDF page rendering, used by the API's page-image endpoint."""

import fitz  # PyMuPDF


def _valid_bbox(bbox: list[float] | None) -> fitz.Rect | None:
    if not bbox or len(bbox) != 4:
        return None
    x0, y0, x1, y1 = bbox
    if x0 >= x1 or y0 >= y1:
        return None
    return fitz.Rect(x0, y0, x1, y1)


def render_page(
    pdf_path: str, page_no: int, bbox: list[float] | None = None
) -> bytes | None:
    """Render a PDF page as PNG bytes, drawing a red box around the evidence if bbox is
    well-formed. A malformed bbox (wrong length, x0>=x1/y0>=y1) is silently ignored — the
    page still renders, just without a highlight. A well-formed but out-of-bounds bbox is
    clamped to the page's own rect before drawing."""
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_no - 1]
        rect = _valid_bbox(bbox)
        if rect is not None:
            rect &= page.rect  # clamp to page bounds (Rect intersection)
            if not rect.is_empty:
                if not doc.is_pdf:
                    # page.draw_rect() writes to a PDF content stream — a page opened
                    # directly from a standalone image (PNG/JPG/etc, a valid upload
                    # type) isn't a real PDF page and can't be drawn on ("is no PDF").
                    # Wrap it in a genuine one-page PDF at the same pixel size first.
                    src_pix = page.get_pixmap()
                    image_doc = doc
                    doc = fitz.open()
                    page = doc.new_page(width=src_pix.width, height=src_pix.height)
                    page.insert_image(page.rect, pixmap=src_pix)
                    image_doc.close()
                page.draw_rect(rect, color=(1, 0, 0), width=2)
        pix = page.get_pixmap(dpi=150)
        return pix.tobytes("png")
    except Exception:
        return None
