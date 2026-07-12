from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import _classify_exception, _run_claim, app
from claimflow import db


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/state.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_transition_package_status_logs_audit_entry(session):
    session.add(db.Package(id="pkg1", status="queued"))
    session.commit()

    db.transition_package_status(session, "pkg1", "processing", reason="process started")

    pkg = session.get(db.Package, "pkg1")
    assert pkg.status == "processing"
    entries = session.query(db.AuditLogEntry).filter_by(package_id="pkg1", action="status_transition").all()
    assert len(entries) == 1
    import json
    detail = json.loads(entries[0].detail_json)
    assert detail == {"from": "queued", "to": "processing", "reason": "process started"}


def test_try_start_processing_rejects_concurrent_call(session):
    session.add(db.Package(id="pkg1", status="queued"))
    session.commit()

    assert db.try_start_processing(session, "pkg1") is True
    assert session.get(db.Package, "pkg1").status == "processing"

    # second call while already processing must lose the race
    assert db.try_start_processing(session, "pkg1") is False


def test_try_start_processing_allows_retry_from_failure_states(session):
    for failure_status in ("processing_error", "validation_error", "retrieval_error", "review_ready", "completed"):
        session.add(db.Package(id=f"pkg-{failure_status}", status=failure_status))
    session.commit()

    for failure_status in ("processing_error", "validation_error", "retrieval_error", "review_ready", "completed"):
        assert db.try_start_processing(session, f"pkg-{failure_status}") is True


def test_extraction_run_attempt_increments_on_reprocess(session):
    session.add(db.Package(id="pkg1", status="queued"))
    session.add(db.Document(id="doc1", package_id="pkg1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.commit()

    run1 = db.create_extraction_run(session, "doc1", "cms1500", "pass", 0.9)
    run2 = db.create_extraction_run(session, "doc1", "cms1500", "pass", 0.95)

    assert run1.attempt == 1
    assert run2.attempt == 2


def test_process_rejects_concurrent_call(monkeypatch):
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

        session = db.SessionLocal()
        db.transition_package_status(session, package_id, "processing", reason="test setup")
        session.close()

        resp = client.post(f"/packages/{package_id}/process")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PROCESSING_IN_PROGRESS"


def test_process_allows_retry_after_processing_error(monkeypatch):
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

        session = db.SessionLocal()
        db.transition_package_status(session, package_id, "processing_error", reason="test setup")
        session.close()

        resp = client.post(f"/packages/{package_id}/process")

    assert resp.status_code == 200


def test_run_claim_classifies_structured_error_as_processing_error(tmp_path):
    graph = MagicMock()
    graph.invoke.return_value = {
        "decision": None, "extraction_data": None, "domain": None, "documents": [],
        "extraction_fields": [], "validation_failures": [], "policy_answers": [],
        "review_reasons": [], "error": "No supported domain detected in package",
    }
    graph.get_state.return_value = MagicMock(values={})

    session = db.SessionLocal()
    db.create_package(session, "pkg-err")
    session.close()

    _run_claim(graph, "pkg-err", tmp_path)

    session = db.SessionLocal()
    pkg = db.get_package(session, "pkg-err")
    assert pkg.status == "processing_error"


def test_run_claim_classifies_approved_decision_as_completed(tmp_path):
    graph = MagicMock()
    graph.invoke.return_value = {
        "decision": "approved", "extraction_data": {}, "domain": "cms1500", "documents": [],
        "extraction_fields": [], "validation_failures": [], "policy_answers": [],
        "review_reasons": [], "error": None,
    }

    session = db.SessionLocal()
    db.create_package(session, "pkg-ok")
    session.close()

    _run_claim(graph, "pkg-ok", tmp_path)

    session = db.SessionLocal()
    pkg = db.get_package(session, "pkg-ok")
    assert pkg.status == "completed"


def test_run_claim_classifies_flagged_decision_as_review_ready(tmp_path):
    graph = MagicMock()
    graph.invoke.return_value = {
        "decision": "flagged", "extraction_data": {}, "domain": "cms1500", "documents": [],
        "extraction_fields": [], "validation_failures": [], "policy_answers": [],
        "review_reasons": ["low confidence"], "error": None,
    }

    session = db.SessionLocal()
    db.create_package(session, "pkg-flag")
    session.close()

    _run_claim(graph, "pkg-flag", tmp_path)

    session = db.SessionLocal()
    pkg = db.get_package(session, "pkg-flag")
    assert pkg.status == "review_ready"


def test_classify_exception_retrieval_error_when_retrieve_should_have_run():
    graph = MagicMock()
    graph.get_state.return_value = MagicMock(
        values={"validation_failures": [{"field": "f", "rule": "r", "reason": "x"}], "extraction_data": {"a": 1}}
    )
    assert _classify_exception(graph, {}) == "retrieval_error"


def test_classify_exception_processing_error_when_validation_passed_and_review_crashed():
    # validation_failures == [] means _should_retrieve routed straight to "review",
    # skipping retrieve entirely -- a crash after this point is not a retrieval_error.
    graph = MagicMock()
    graph.get_state.return_value = MagicMock(
        values={"validation_failures": [], "extraction_data": {"a": 1}}
    )
    assert _classify_exception(graph, {}) == "processing_error"


def test_classify_exception_validation_error_when_extraction_done_but_no_validation():
    graph = MagicMock()
    graph.get_state.return_value = MagicMock(
        values={"extraction_data": {"a": 1}, "validation_failures": None, "policy_answers": []}
    )
    assert _classify_exception(graph, {}) == "validation_error"


def test_classify_exception_processing_error_when_no_state_reached():
    graph = MagicMock()
    graph.get_state.return_value = MagicMock(values={})
    assert _classify_exception(graph, {}) == "processing_error"


def test_classify_exception_processing_error_when_get_state_raises():
    graph = MagicMock()
    graph.get_state.side_effect = RuntimeError("no checkpoint")
    assert _classify_exception(graph, {}) == "processing_error"


def test_classify_exception_against_real_graph_state(monkeypatch):
    """Build a real compiled graph (real MemorySaver checkpointer), crash a real
    node, and confirm get_state(config).values genuinely omits unwritten channels
    (rather than holding them as None) -- the assumption _classify_exception relies on."""
    import claimflow.graph as graph_module

    def fake_ingest(state):
        return {
            "documents": [{
                "path": "x.pdf", "doc_type": "cms1500", "has_text_layer": True,
                "scan_quality": None, "classification_reason": "test",
            }],
            "domain": "cms1500", "ocr_log": [],
        }

    def fake_extract(state):
        return {
            "extraction_data": {"field": "value"}, "extraction_fields": [],
            "extraction_status": "pass", "extraction_overall_confidence": 0.9,
        }

    def fake_validate(state):
        return {"validation_failures": [{"field": "f", "rule": "r", "reason": "simulated failure"}]}

    def crashing_retrieve(state):
        raise RuntimeError("simulated retrieval crash")

    monkeypatch.setattr(graph_module, "ingest_node", fake_ingest)
    monkeypatch.setattr(graph_module, "extract_node", fake_extract)
    monkeypatch.setattr(graph_module, "validate_node", fake_validate)
    monkeypatch.setattr(graph_module, "retrieve_node", crashing_retrieve)

    graph = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-real-graph-thread"}}

    with pytest.raises(RuntimeError, match="simulated retrieval crash"):
        graph.invoke({"package_dir": "unused", "domain": None, "doc_type_overrides": {}}, config=config)

    values = graph.get_state(config).values

    # Empirical confirmation: retrieve's output channel is absent, not None.
    assert "policy_answers" not in values
    assert values["validation_failures"] == [{"field": "f", "rule": "r", "reason": "simulated failure"}]

    assert _classify_exception(graph, config) == "retrieval_error"
