import uuid

from fastapi.testclient import TestClient

from api.main import app
from claimflow import db


def test_get_package_review_returns_fields_and_failures():
    session = db.SessionLocal()
    try:
        pkg = db.create_package(session, str(uuid.uuid4()))
        doc = db.create_document(session, pkg.id, {
            "path": "/tmp/claim.pdf", "doc_type": "cms1500",
            "has_text_layer": True, "scan_quality": None,
        })
        run = db.create_extraction_run(session, doc.id, "cms1500", "review", 0.5)
        fields = db.create_extracted_fields(session, run.id, [
            {"name": "patient_name", "value": "DOE JOHN", "confidence": 0.91,
             "grounded": True, "valid": True, "field_status": "found", "evidence": None},
        ])
        db.create_validation_failures(session, run.id, [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "bad code"},
        ])
        field_id = fields[0].id
        package_id = pkg.id
        package_status = pkg.status
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/{package_id}/review")

    assert resp.status_code == 200
    body = resp.json()
    assert body["package_id"] == package_id
    assert body["status"] == package_status

    assert len(body["fields"]) == 1
    field = body["fields"][0]
    assert field["field_id"] == field_id
    assert field["name"] == "patient_name"
    assert field["value"] == "DOE JOHN"
    assert field["confidence"] == 0.91
    assert field["field_status"] == "found"

    assert len(body["validation_failures"]) == 1
    failure = body["validation_failures"][0]
    assert failure["field"] == "diagnosis_codes"
    assert failure["rule"] == "icd10_lookup"
    assert failure["reason"] == "bad code"


def test_get_package_review_exposes_latest_reviewer_action():
    session = db.SessionLocal()
    try:
        pkg = db.create_package(session, str(uuid.uuid4()))
        doc = db.create_document(session, pkg.id, {
            "path": "/tmp/claim.pdf", "doc_type": "cms1500",
            "has_text_layer": True, "scan_quality": None,
        })
        run = db.create_extraction_run(session, doc.id, "cms1500", "review", 0.5)
        db.create_extracted_fields(session, run.id, [
            {"name": "claim_number", "value": None, "confidence": 0.3,
             "grounded": False, "valid": True, "field_status": "not_found", "evidence": None},
        ])
        db.record_review_action(
            session, run.id, "claim_number", "edit",
            original_value=None, corrected_value="CLM-9001", reviewer="jane", note="typed in from cover letter",
        )
        package_id = pkg.id
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/{package_id}/review")

    field = resp.json()["fields"][0]
    assert field["reviewer_action"] == "edit"
    assert field["corrected_value"] == "CLM-9001"
    assert field["reviewer"] == "jane"
    assert field["reviewer_note"] == "typed in from cover letter"


def test_get_package_review_field_without_review_action_has_null_reviewer_fields():
    session = db.SessionLocal()
    try:
        pkg = db.create_package(session, str(uuid.uuid4()))
        doc = db.create_document(session, pkg.id, {
            "path": "/tmp/claim.pdf", "doc_type": "cms1500",
            "has_text_layer": True, "scan_quality": None,
        })
        run = db.create_extraction_run(session, doc.id, "cms1500", "review", 0.5)
        db.create_extracted_fields(session, run.id, [
            {"name": "patient_name", "value": "DOE JOHN", "confidence": 0.91,
             "grounded": True, "valid": True, "field_status": "found", "evidence": None},
        ])
        package_id = pkg.id
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/{package_id}/review")

    field = resp.json()["fields"][0]
    assert field["reviewer_action"] is None
    assert field["corrected_value"] is None
    assert field["reviewer"] is None
    assert field["reviewer_note"] is None


def test_evidence_404_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/pkg/fields/999999/evidence")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FIELD_NOT_FOUND"


def test_reviews_queue_shape():
    with TestClient(app) as client:
        resp = client.get("/reviews/queue")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
