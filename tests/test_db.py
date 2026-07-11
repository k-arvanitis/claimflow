import json
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_all_tables_created():
    session = _make_session()
    inspector_tables = db.Base.metadata.tables.keys()
    expected = {
        "packages", "audit_log", "documents", "extraction_runs",
        "extracted_fields", "validation_failures", "policy_evidence",
        "decisions", "review_actions",
    }
    assert expected.issubset(inspector_tables)
    session.close()


def test_create_document_and_extraction_run():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    doc = db.create_document(session, pkg.id, {
        "path": "/tmp/claim.pdf", "doc_type": "cms1500",
        "has_text_layer": True, "scan_quality": None,
    })
    assert doc.package_id == pkg.id
    assert doc.doc_type == "cms1500"

    run = db.create_extraction_run(session, doc.id, "cms1500", "pass", 0.91)
    assert run.document_id == doc.id
    assert run.status == "pass"

    fields = db.create_extracted_fields(session, run.id, [
        {"name": "patient_name", "value": "DOE JOHN", "confidence": 0.95,
         "grounded": True, "valid": True, "field_status": "found", "evidence": None},
    ])
    assert len(fields) == 1
    assert fields[0].extraction_run_id == run.id
    assert json.loads(fields[0].value_json) == "DOE JOHN"

    failures = db.create_validation_failures(session, run.id, [
        {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "'XXXXX' is not a recognized ICD-10-CM code"},
    ])
    assert len(failures) == 1
    assert failures[0].rule == "icd10_lookup"
    session.close()


def test_create_policy_evidence_and_decision():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    evidence = db.create_policy_evidence(session, pkg.id, [
        {"question": "Is diagnosis code XXXXX billable?", "answer": "No, it is not a recognized code.",
         "citations": ["policy excerpt [1]"]},
    ])
    assert len(evidence) == 1
    assert json.loads(evidence[0].citations_json) == ["policy excerpt [1]"]

    decision = db.create_decision(session, pkg.id, "flagged", ["diagnosis_codes: not a recognized code"])
    assert decision.decision == "flagged"
    assert json.loads(decision.review_reasons_json) == ["diagnosis_codes: not a recognized code"]
    session.close()
