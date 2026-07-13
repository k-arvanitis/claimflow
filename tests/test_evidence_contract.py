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


def test_evidence_points_to_correct_field_after_reprocess_creates_new_run(session_factory):
    session = session_factory()
    session.add(db.Package(id="pkg1", status="review_ready"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.commit()

    run1 = db.create_extraction_run(session, "doc1", "cms1500", "review", 0.7)
    fields1 = db.create_extracted_fields(session, run1.id, [
        {"name": "patient_name", "value": "DOE JOHN", "confidence": 0.7, "grounded": True, "valid": True,
         "field_status": "review", "evidence": {"page": 1, "text": "old quote", "bbox": None, "block_type": "paragraph"}},
    ])

    # simulate a reprocess: a NEW ExtractionRun (attempt 2) with its own field/evidence
    run2 = db.create_extraction_run(session, "doc1", "cms1500", "pass", 0.95)
    fields2 = db.create_extracted_fields(session, run2.id, [
        {"name": "patient_name", "value": "DOE JOHN", "confidence": 0.95, "grounded": True, "valid": True,
         "field_status": "found", "evidence": {"page": 1, "text": "new quote", "bbox": [1.0, 2.0, 3.0, 4.0], "block_type": "paragraph"}},
    ])
    # capture attributes while still attached — session.commit() (inside
    # create_extracted_fields) expires prior objects' attributes by default,
    # and they can't be reloaded once the session is closed below.
    attempt1, attempt2 = run1.attempt, run2.attempt
    field1_id, field2_id = fields1[0].id, fields2[0].id
    session.close()

    assert attempt2 == attempt1 + 1

    with TestClient(app) as client:
        old_resp = client.get(f"/packages/pkg1/fields/{field1_id}/evidence")
        new_resp = client.get(f"/packages/pkg1/fields/{field2_id}/evidence")

    assert old_resp.json()["quote"] == "old quote"  # attempt 1's evidence is untouched
    assert new_resp.json()["quote"] == "new quote"  # attempt 2's evidence is independent
