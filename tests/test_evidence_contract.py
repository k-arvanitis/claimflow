import json

from fastapi.testclient import TestClient

from api.main import app
from claimflow import db


def _seed_field_with_evidence(session, evidence=None):
    session.add(db.Package(id="pkg1", status="review_ready"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="/tmp/a.pdf", doc_type="cms1500", has_text_layer=True))
    session.add(db.ExtractionRun(id="run1", document_id="doc1", schema_name="cms1500", status="review", overall_confidence=0.8))
    field = db.ExtractedField(
        extraction_run_id="run1", name="patient_name", value_json=json.dumps("DOE JOHN"),
        confidence=0.8, grounded=True, valid=True, field_status="review",
        evidence_json=json.dumps(evidence) if evidence is not None else None,
    )
    session.add(field)
    session.commit()
    session.refresh(field)  # warm attributes while still attached, before caller closes the session
    return field


def test_evidence_response_has_full_contract_shape(session_factory):
    session = session_factory()
    field = _seed_field_with_evidence(session, {
        "page": 1, "text": "Patient's Name: John Smith", "bbox": [120.0, 244.0, 310.0, 260.0], "block_type": "paragraph",
    })
    session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/pkg1/fields/{field.id}/evidence")

    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == "doc1"
    assert body["filename"] == "a.pdf"
    assert body["page"] == 1
    assert body["quote"] == "Patient's Name: John Smith"
    assert body["bbox"] == [120.0, 244.0, 310.0, 260.0]
    assert body["coordinate_system"] == "pdf_points"
    assert body["block_type"] == "paragraph"
    assert body["evidence_unavailable"] is False


def test_evidence_missing_geometry_returns_null_bbox_and_unavailable_flag(session_factory):
    session = session_factory()
    field = _seed_field_with_evidence(session, evidence=None)
    session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/pkg1/fields/{field.id}/evidence")

    body = resp.json()
    assert body["bbox"] is None
    assert body["page"] is None
    assert body["evidence_unavailable"] is True


def test_evidence_malformed_bbox_rejected_to_null(session_factory):
    session = session_factory()
    field = _seed_field_with_evidence(session, {
        "page": 1, "text": "x", "bbox": [1.0, 2.0], "block_type": "paragraph",  # wrong length
    })
    session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/pkg1/fields/{field.id}/evidence")

    assert resp.json()["bbox"] is None


def test_render_page_clamps_out_of_bounds_bbox(tmp_path):
    import fitz

    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    doc.save(str(pdf_path))
    doc.close()

    from claimflow.pages import render_page

    # bbox extends far past the page — must not raise, must still render
    result = render_page(str(pdf_path), 1, [500.0, 700.0, 2000.0, 2000.0])
    assert result is not None


def test_render_page_ignores_malformed_bbox(tmp_path):
    import fitz

    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    doc.save(str(pdf_path))
    doc.close()

    from claimflow.pages import render_page

    result = render_page(str(pdf_path), 1, [1.0, 2.0])  # wrong length
    assert result is not None  # renders the page without the highlight, doesn't crash
