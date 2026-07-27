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
        "packages",
        "audit_log",
        "documents",
        "extraction_runs",
        "extracted_fields",
        "validation_failures",
        "policy_evidence",
        "decisions",
        "review_actions",
    }
    assert expected.issubset(inspector_tables)
    session.close()


def test_create_document_and_extraction_run():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    doc = db.create_document(
        session,
        pkg.id,
        {
            "path": "/tmp/claim.pdf",
            "doc_type": "cms1500",
            "has_text_layer": True,
            "scan_quality": None,
        },
    )
    assert doc.package_id == pkg.id
    assert doc.doc_type == "cms1500"

    run = db.create_extraction_run(session, doc.id, "cms1500", "pass", 0.91)
    assert run.document_id == doc.id
    assert run.status == "pass"

    fields = db.create_extracted_fields(
        session,
        run.id,
        [
            {
                "name": "patient_name",
                "value": "DOE JOHN",
                "confidence": 0.95,
                "grounded": True,
                "valid": True,
                "field_status": "found",
                "evidence": None,
            },
        ],
    )
    assert len(fields) == 1
    assert fields[0].extraction_run_id == run.id
    assert json.loads(fields[0].value_json) == "DOE JOHN"

    failures = db.create_validation_failures(
        session,
        run.id,
        [
            {
                "field": "diagnosis_codes",
                "rule": "icd10_lookup",
                "reason": "'XXXXX' is not a recognized ICD-10-CM code",
            },
        ],
    )
    assert len(failures) == 1
    assert failures[0].rule == "icd10_lookup"
    session.close()


def test_create_policy_evidence_and_decision():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    evidence = db.create_policy_evidence(
        session,
        pkg.id,
        [
            {
                "question": "Is diagnosis code XXXXX billable?",
                "answer": "No, it is not a recognized code.",
                "citations": ["policy excerpt [1]"],
            },
        ],
    )
    assert len(evidence) == 1
    assert json.loads(evidence[0].citations_json) == ["policy excerpt [1]"]

    decision = db.create_decision(
        session, pkg.id, "flagged", ["diagnosis_codes: not a recognized code"]
    )
    assert decision.decision == "flagged"
    assert json.loads(decision.review_reasons_json) == [
        "diagnosis_codes: not a recognized code"
    ]
    session.close()


def test_replace_policy_evidence_removes_stale_reprocessing_answers():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    db.create_policy_evidence(
        session,
        pkg.id,
        [{"question": "old", "answer": "old", "citations": []}],
    )

    db.replace_policy_evidence(
        session,
        pkg.id,
        [{"question": "current", "answer": "current", "citations": ["source"]}],
    )

    [evidence] = db.list_policy_evidence_for_package(session, pkg.id)
    assert evidence.question == "current"

    db.replace_policy_evidence(session, pkg.id, [])
    assert db.list_policy_evidence_for_package(session, pkg.id) == []
    session.close()


def test_record_review_action_keeps_original_and_corrected_separate():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    doc = db.create_document(
        session,
        pkg.id,
        {
            "path": "/tmp/claim.pdf",
            "doc_type": "cms1500",
            "has_text_layer": True,
            "scan_quality": None,
        },
    )
    run = db.create_extraction_run(session, doc.id, "cms1500", "review", 0.6)

    action = db.record_review_action(
        session,
        run.id,
        "diagnosis_codes",
        "edit",
        original_value=["XXXXX"],
        corrected_value=["J06.9"],
        validation_before=["'XXXXX' is not a recognized ICD-10-CM code"],
        validation_after=[],
        reviewer="jane.reviewer",
        note="Corrected after checking the source document.",
    )
    assert action.action == "edit"
    assert json.loads(action.original_value_json) == ["XXXXX"]
    assert json.loads(action.corrected_value_json) == ["J06.9"]
    assert json.loads(action.validation_before_json) == [
        "'XXXXX' is not a recognized ICD-10-CM code"
    ]
    assert json.loads(action.validation_after_json) == []
    assert action.reviewer == "jane.reviewer"
    session.close()


def test_persist_extraction_result_writes_all_rows():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))

    result = {
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
            }
        ],
        "extraction_status": "review",
        "extraction_overall_confidence": 0.6,
        "extraction_fields": [
            {
                "name": "diagnosis_codes",
                "value": ["XXXXX"],
                "confidence": 0.5,
                "grounded": True,
                "valid": False,
                "field_status": "found",
                "evidence": None,
            },
        ],
        "validation_failures": [
            {
                "field": "diagnosis_codes",
                "rule": "icd10_lookup",
                "reason": "'XXXXX' is not a recognized ICD-10-CM code",
            },
        ],
        "policy_answers": [
            {
                "question": "Is diagnosis code XXXXX billable?",
                "answer": "No.",
                "citations": ["policy excerpt [1]"],
            },
        ],
        "decision": "flagged",
        "review_reasons": [
            "diagnosis_codes: 'XXXXX' is not a recognized ICD-10-CM code"
        ],
    }

    db.persist_extraction_result(session, pkg.id, result)

    assert session.query(db.Document).filter_by(package_id=pkg.id).count() == 1
    assert session.query(db.ExtractionRun).count() == 1
    assert session.query(db.ExtractedField).count() == 1
    assert session.query(db.ValidationFailure).count() == 1
    assert session.query(db.PolicyEvidence).filter_by(package_id=pkg.id).count() == 1
    assert session.query(db.Decision).filter_by(package_id=pkg.id).count() == 1
    session.close()


def test_list_and_get_package():
    session = _make_session()
    pkg1 = db.create_package(session, str(uuid.uuid4()))
    pkg2 = db.create_package(session, str(uuid.uuid4()))

    all_pkgs = db.list_packages(session)
    assert {p.id for p in all_pkgs} == {pkg1.id, pkg2.id}

    fetched = db.get_package(session, pkg1.id)
    assert fetched.id == pkg1.id
    assert db.get_package(session, "does-not-exist") is None
    session.close()


def test_delete_package_cascades():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    doc = db.create_document(
        session,
        pkg.id,
        {
            "path": "/tmp/claim.pdf",
            "doc_type": "cms1500",
            "has_text_layer": True,
            "scan_quality": None,
        },
    )
    run = db.create_extraction_run(session, doc.id, "cms1500", "pass", 0.9)
    db.create_extracted_fields(
        session,
        run.id,
        [
            {
                "name": "patient_name",
                "value": "DOE JOHN",
                "confidence": 0.9,
                "grounded": True,
                "valid": True,
                "field_status": "found",
                "evidence": None,
            },
        ],
    )
    db.create_validation_failures(
        session,
        run.id,
        [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "bad code"},
        ],
    )
    db.create_policy_evidence(
        session,
        pkg.id,
        [
            {"question": "q", "answer": "a", "citations": []},
        ],
    )
    db.create_decision(session, pkg.id, "flagged", ["bad code"])
    db.record_review_action(session, run.id, "patient_name", "approve")

    pkg_id, doc_id, run_id = pkg.id, doc.id, run.id

    deleted = db.delete_package(session, pkg_id)
    assert deleted is True
    assert db.get_package(session, pkg_id) is None
    assert session.query(db.Document).filter_by(package_id=pkg_id).count() == 0
    assert session.query(db.ExtractionRun).filter_by(document_id=doc_id).count() == 0
    assert (
        session.query(db.ExtractedField).filter_by(extraction_run_id=run_id).count()
        == 0
    )
    assert (
        session.query(db.ValidationFailure).filter_by(extraction_run_id=run_id).count()
        == 0
    )
    assert session.query(db.PolicyEvidence).filter_by(package_id=pkg_id).count() == 0
    assert session.query(db.Decision).filter_by(package_id=pkg_id).count() == 0
    assert (
        session.query(db.ReviewAction).filter_by(extraction_run_id=run_id).count() == 0
    )
    assert db.delete_package(session, "does-not-exist") is False
    session.close()


def test_document_and_field_lookups():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    doc = db.create_document(
        session,
        pkg.id,
        {
            "path": "/tmp/claim.pdf",
            "doc_type": "cms1500",
            "has_text_layer": True,
            "scan_quality": None,
        },
    )
    run = db.create_extraction_run(session, doc.id, "cms1500", "pass", 0.9)
    fields = db.create_extracted_fields(
        session,
        run.id,
        [
            {
                "name": "patient_name",
                "value": "DOE JOHN",
                "confidence": 0.9,
                "grounded": True,
                "valid": True,
                "field_status": "found",
                "evidence": None,
            },
        ],
    )
    failures = db.create_validation_failures(
        session,
        run.id,
        [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "bad code"},
        ],
    )

    assert [d.id for d in db.list_documents(session, pkg.id)] == [doc.id]
    assert db.get_document(session, doc.id).id == doc.id
    assert db.get_document(session, "nope") is None
    assert db.get_extracted_field(session, fields[0].id).id == fields[0].id
    assert db.get_extracted_field(session, -1) is None
    assert [f.id for f in db.list_extracted_fields_for_run(session, run.id)] == [
        fields[0].id
    ]
    assert [f.id for f in db.list_validation_failures_for_run(session, run.id)] == [
        failures[0].id
    ]
    assert db.latest_extraction_run_for_package(session, pkg.id).id == run.id
    session.close()


def test_decision_and_audit_lookups():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    db.create_decision(session, pkg.id, "flagged", ["first"])
    latest = db.create_decision(session, pkg.id, "escalated", ["second"])
    db.log_audit(session, pkg.id, "api", "upload")

    assert db.latest_decision_for_package(session, pkg.id).id == latest.id
    assert len(db.list_decisions_for_package(session, pkg.id)) == 2
    assert len(db.list_audit_events_for_package(session, pkg.id)) == 1
    db.create_policy_evidence(
        session, pkg.id, [{"question": "q", "answer": "a", "citations": []}]
    )
    assert len(db.list_policy_evidence_for_package(session, pkg.id)) == 1

    flagged = db.list_flagged_packages(session)
    assert pkg.id in {p.id for p in flagged}
    session.close()


def test_create_document_persists_classification_reason():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    doc = db.create_document(
        session,
        pkg.id,
        {
            "path": "/tmp/claim.pdf",
            "doc_type": "cms1500",
            "has_text_layer": True,
            "scan_quality": None,
            "classification_reason": "matched domain keyword 'cms-1500' for cms1500",
        },
    )
    assert doc.classification_reason == "matched domain keyword 'cms-1500' for cms1500"
    assert doc.manually_overridden is False

    overridden = db.create_document(
        session,
        pkg.id,
        {
            "path": "/tmp/other.pdf",
            "doc_type": "eob",
            "has_text_layer": True,
            "scan_quality": None,
            "classification_reason": "manual override",
            "manually_overridden": True,
        },
    )
    assert overridden.manually_overridden is True
    session.close()


def test_create_document_preserves_manually_overridden_on_reprocess():
    session = _make_session()
    pkg = db.create_package(session, str(uuid.uuid4()))
    doc = db.create_document(
        session,
        pkg.id,
        {
            "path": "/tmp/claim.pdf",
            "doc_type": "eob",
            "has_text_layer": True,
            "scan_quality": None,
            "classification_reason": "manual override",
            "manually_overridden": True,
        },
    )
    assert doc.manually_overridden is True

    # simulate a second reprocess: ingest's dict never carries manually_overridden
    reprocessed = db.create_document(
        session,
        pkg.id,
        {
            "path": "/tmp/claim.pdf",
            "doc_type": "eob",
            "has_text_layer": True,
            "scan_quality": None,
            "classification_reason": "manual override",
        },
    )
    assert reprocessed.id == doc.id
    assert reprocessed.manually_overridden is True
    session.close()
