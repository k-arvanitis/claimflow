import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/dashboard.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _pkg_with_decision(session, package_id, status, decision=None, decision_age_days=0):
    from datetime import datetime, timedelta, timezone
    session.add(db.Package(id=package_id, status=status))
    session.commit()
    if decision:
        row = db.create_decision(session, package_id, decision, [])
        row.created_at = datetime.now(timezone.utc) - timedelta(days=decision_age_days)
        session.commit()


def test_dashboard_summary_counts_by_status(session):
    _pkg_with_decision(session, "p1", "processing")
    _pkg_with_decision(session, "p2", "processing")
    _pkg_with_decision(session, "p3", "review_ready", "flagged")
    _pkg_with_decision(session, "p4", "completed", "approved")
    _pkg_with_decision(session, "p5", "processing_error")

    summary = db.compute_dashboard_summary(session)

    assert summary["total_packages"] == 5
    assert summary["processing"] == 2
    assert summary["awaiting_review"] == 1
    assert summary["approved"] == 1
    assert summary["processing_errors"] == 1


def test_dashboard_summary_splits_flagged_vs_escalated_by_latest_decision(session):
    _pkg_with_decision(session, "p1", "review_ready", "flagged")
    _pkg_with_decision(session, "p2", "review_ready", "escalated")
    _pkg_with_decision(session, "p3", "review_ready", "escalated")

    summary = db.compute_dashboard_summary(session)

    assert summary["flagged"] == 1
    assert summary["escalated"] == 2


def test_dashboard_summary_uses_latest_decision_not_first(session):
    session.add(db.Package(id="p1", status="review_ready"))
    session.commit()
    db.create_decision(session, "p1", "escalated", [])
    db.create_decision(session, "p1", "flagged", [])  # reviewer downgraded it later

    summary = db.compute_dashboard_summary(session)

    assert summary["flagged"] == 1
    assert summary["escalated"] == 0


def test_straight_through_rate_computed_from_decided_packages(session):
    _pkg_with_decision(session, "p1", "completed", "approved")
    _pkg_with_decision(session, "p2", "completed", "approved")
    _pkg_with_decision(session, "p3", "review_ready", "flagged")

    summary = db.compute_dashboard_summary(session)

    assert summary["straight_through_rate"] == pytest.approx(2 / 3)


def test_straight_through_rate_zero_when_no_decisions(session):
    _pkg_with_decision(session, "p1", "processing")

    summary = db.compute_dashboard_summary(session)

    assert summary["straight_through_rate"] == 0.0


def test_top_validation_failures_ranked_by_count(session):
    session.add(db.Package(id="p1", status="review_ready"))
    session.add(db.Document(id="d1", package_id="p1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.commit()
    run = db.create_extraction_run(session, "d1", "cms1500", "review", 0.7)
    db.create_validation_failures(session, run.id, [
        {"field": "npi", "rule": "npi_format", "reason": "x"},
        {"field": "npi2", "rule": "npi_format", "reason": "x"},
        {"field": "dob", "rule": "date_range", "reason": "x"},
    ])

    summary = db.compute_dashboard_summary(session)

    assert summary["top_validation_failures"][0] == {"rule": "npi_format", "count": 2}
    assert summary["top_validation_failures"][1] == {"rule": "date_range", "count": 1}


def test_top_validation_failures_excludes_superseded(session):
    session.add(db.Package(id="p1", status="review_ready"))
    session.add(db.Document(id="d1", package_id="p1", path="a.pdf", doc_type="cms1500", has_text_layer=True))
    session.commit()
    run = db.create_extraction_run(session, "d1", "cms1500", "review", 0.7)
    db.create_validation_failures(session, run.id, [{"field": "npi", "rule": "npi_format", "reason": "x"}])
    db.supersede_validation_failures(session, run.id)
    db.create_validation_failures(session, run.id, [{"field": "dob", "rule": "date_range", "reason": "x"}])

    summary = db.compute_dashboard_summary(session)

    rules = {item["rule"] for item in summary["top_validation_failures"]}
    assert "npi_format" not in rules
    assert "date_range" in rules
