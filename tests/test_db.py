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


def test_record_review_action_keeps_original_and_corrected_separate():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    doc = db.create_document(session, pkg.id, {
        "path": "/tmp/claim.pdf", "doc_type": "cms1500", "has_text_layer": True, "scan_quality": None,
    })
    run = db.create_extraction_run(session, doc.id, "cms1500", "review", 0.6)

    action = db.record_review_action(
        session, run.id, "diagnosis_codes", "edit",
        original_value=["XXXXX"], corrected_value=["J06.9"],
        validation_before=["'XXXXX' is not a recognized ICD-10-CM code"],
        validation_after=[],
        reviewer="jane.reviewer",
        note="Corrected after checking the source document.",
    )
    assert action.action == "edit"
    assert json.loads(action.original_value_json) == ["XXXXX"]
    assert json.loads(action.corrected_value_json) == ["J06.9"]
    assert json.loads(action.validation_before_json) == ["'XXXXX' is not a recognized ICD-10-CM code"]
    assert json.loads(action.validation_after_json) == []
    assert action.reviewer == "jane.reviewer"
    session.close()


def test_persist_extraction_result_writes_all_rows():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    result = {
        "domain": "cms1500",
        "documents": [{"path": "/tmp/claim.pdf", "doc_type": "cms1500", "has_text_layer": True, "scan_quality": None}],
        "extraction_status": "review",
        "extraction_overall_confidence": 0.6,
        "extraction_fields": [
            {"name": "diagnosis_codes", "value": ["XXXXX"], "confidence": 0.5,
             "grounded": True, "valid": False, "field_status": "found", "evidence": None},
        ],
        "validation_failures": [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "'XXXXX' is not a recognized ICD-10-CM code"},
        ],
        "policy_answers": [
            {"question": "Is diagnosis code XXXXX billable?", "answer": "No.", "citations": ["policy excerpt [1]"]},
        ],
        "decision": "flagged",
        "review_reasons": ["diagnosis_codes: 'XXXXX' is not a recognized ICD-10-CM code"],
    }

    db.persist_extraction_result(session, pkg.id, result)

    assert session.query(db.Document).filter_by(package_id=pkg.id).count() == 1
    assert session.query(db.ExtractionRun).count() == 1
    assert session.query(db.ExtractedField).count() == 1
    assert session.query(db.ValidationFailure).count() == 1
    assert session.query(db.PolicyEvidence).filter_by(package_id=pkg.id).count() == 1
    assert session.query(db.Decision).filter_by(package_id=pkg.id).count() == 1
    session.close()
