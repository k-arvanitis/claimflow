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
