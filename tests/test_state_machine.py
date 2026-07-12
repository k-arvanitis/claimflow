import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
