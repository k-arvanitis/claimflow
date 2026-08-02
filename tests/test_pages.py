import fitz

from claimflow.pages import render_page


def test_render_page_returns_png_bytes(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Hello")
    doc.save(str(pdf_path))
    doc.close()

    result = render_page(str(pdf_path), 1, bbox=None)
    assert result is not None
    assert result.startswith(b"\x89PNG")


def test_render_page_with_bbox_highlight(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Hello")
    doc.save(str(pdf_path))
    doc.close()

    result = render_page(str(pdf_path), 1, bbox=[10.0, 10.0, 100.0, 100.0])
    assert result is not None
    assert result.startswith(b"\x89PNG")


def test_render_page_returns_none_for_bad_path():
    assert render_page("/no/such/file.pdf", 1, bbox=None) is None


def test_render_page_with_bbox_highlight_on_standalone_image(tmp_path):
    """Regression: page.draw_rect() writes to a PDF content stream, but a page
    opened directly from a standalone image (a valid upload type — PNG/JPG/etc,
    not embedded in a PDF) isn't a real PDF page ("is no PDF") and can't be drawn
    on. Before the fix this raised inside render_page()'s try/except and silently
    returned None — every image-sourced OCR'd document lost evidence highlighting
    entirely, with no error surfaced anywhere."""
    img_path = tmp_path / "test.png"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(0, 0, 200, 200), color=(1, 1, 1), fill=(1, 1, 1))
    pix = page.get_pixmap()
    pix.save(str(img_path))
    doc.close()

    result = render_page(str(img_path), 1, bbox=[10.0, 10.0, 100.0, 100.0])
    assert result is not None
    assert result.startswith(b"\x89PNG")
