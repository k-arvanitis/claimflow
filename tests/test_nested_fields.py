import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fastapi.testclient import TestClient

from api.main import app
from claimflow import db


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/nested_fields.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_row_field_persists_parent_field(session):
    session.add(db.Package(id="pkg1", status="review_ready"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.add(db.ExtractionRun(id="run1", document_id="doc1", schema_name="cms1500", status="review", overall_confidence=0.8))
    session.commit()

    rows = db.create_extracted_fields(session, "run1", [
        {"name": "service_lines", "value": [{"cpt_code": "99213"}], "confidence": 0.9, "grounded": True, "valid": True, "field_status": "found"},
        {"name": "service_lines[0]", "value": {"cpt_code": "99213"}, "confidence": 0.85, "grounded": True, "valid": True,
         "field_status": "found", "parent_field": "service_lines", "evidence": {"page": 2, "text": "99213", "bbox": [10.0, 20.0, 30.0, 40.0], "block_type": "table_cell"}},
    ])

    parent = next(r for r in rows if r.name == "service_lines")
    row = next(r for r in rows if r.name == "service_lines[0]")
    assert parent.parent_field is None
    assert row.parent_field == "service_lines"


def test_get_package_review_exposes_parent_field_for_rows(session_factory):
    session = session_factory()
    try:
        pkg = db.create_package(session, str(uuid.uuid4()))
        doc = db.create_document(session, pkg.id, {
            "path": "/tmp/claim.pdf", "doc_type": "cms1500",
            "has_text_layer": True, "scan_quality": None,
        })
        run = db.create_extraction_run(session, doc.id, "cms1500", "review", 0.5)
        fields = db.create_extracted_fields(session, run.id, [
            {"name": "service_lines", "value": [{"cpt_code": "99213"}], "confidence": 0.9,
             "grounded": True, "valid": True, "field_status": "found", "evidence": None},
            {"name": "service_lines[0]", "value": {"cpt_code": "99213"}, "confidence": 0.85,
             "grounded": True, "valid": True, "field_status": "found", "parent_field": "service_lines",
             "evidence": None},
        ])
        field_ids = {f.name: f.id for f in fields}
        package_id = pkg.id
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/{package_id}/review")

    assert resp.status_code == 200
    body = resp.json()
    fields_by_id = {f["field_id"]: f for f in body["fields"]}

    parent = fields_by_id[field_ids["service_lines"]]
    row = fields_by_id[field_ids["service_lines[0]"]]

    assert parent["parent_field"] is None
    assert row["parent_field"] == "service_lines"


def test_row_field_reviewed_independently_of_parent(session_factory):
    session = session_factory()
    session.add(db.Package(id="pkg1", status="review_ready"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.add(db.ExtractionRun(id="run1", document_id="doc1", schema_name="cms1500", status="review", overall_confidence=0.8))
    session.commit()
    rows = db.create_extracted_fields(session, "run1", [
        {"name": "service_lines[0]", "value": {"cpt_code": "99213"}, "confidence": 0.85, "grounded": True,
         "valid": True, "field_status": "found", "parent_field": "service_lines"},
    ])
    row_field_id = rows[0].id
    session.close()

    with TestClient(app) as client:
        resp = client.post(
            f"/packages/pkg1/fields/{row_field_id}/review",
            json={"action": "edit", "corrected_value": {"cpt_code": "99214"}, "reviewer": "alice"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["corrected_value"] == {"cpt_code": "99214"}

    session = session_factory()
    action = session.query(db.ReviewAction).filter_by(extraction_run_id="run1", field_name="service_lines[0]").one()
    assert json.loads(action.corrected_value_json) == {"cpt_code": "99214"}
    session.close()


def test_evidence_unavailable_for_scalar_list_item_without_row_scoring(session_factory):
    # diagnosis_codes is list[str] — doc-intel never produces per-item FieldConfidence for
    # it, so it persists as ONE ExtractedField ("diagnosis_codes") with the whole list as
    # its value; there is no synthetic "diagnosis_codes[0]" row to review independently.
    # This test documents that behavior rather than fabricating one.
    session = session_factory()
    session.add(db.Package(id="pkg1", status="review_ready"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.add(db.ExtractionRun(id="run1", document_id="doc1", schema_name="cms1500", status="review", overall_confidence=0.8))
    session.commit()
    db.create_extracted_fields(session, "run1", [
        {"name": "diagnosis_codes", "value": ["J06.9"], "confidence": 0.9, "grounded": True,
         "valid": True, "field_status": "found", "evidence": None},
    ])
    session.close()

    with TestClient(app) as client:
        resp = client.get("/packages/pkg1/review")

    fields = resp.json()["fields"]
    assert len(fields) == 1
    assert fields[0]["parent_field"] is None  # no row-level breakdown exists for this field
