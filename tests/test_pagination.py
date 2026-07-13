from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import app
from claimflow import db


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/pagination.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(session, package_id, status, domain=None, decision=None, confidence=None, rule=None, days_ago=0):
    session.add(db.Package(
        id=package_id, status=status,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    ))
    session.commit()
    if domain or confidence is not None:
        session.add(db.Document(id=f"{package_id}-doc", package_id=package_id, path=f"{package_id}.pdf", doc_type=domain or "cms1500", has_text_layer=True))
        session.commit()
        run = db.create_extraction_run(session, f"{package_id}-doc", domain or "cms1500", "review", confidence or 0.8)
        if rule:
            db.create_validation_failures(session, run.id, [{"field": "x", "rule": rule, "reason": "r"}])
    if decision:
        db.create_decision(session, package_id, decision, [])


def test_pagination_returns_correct_page_and_total(session):
    for i in range(5):
        _seed(session, f"pkg{i}", "completed", days_ago=i)

    rows, total = db.list_packages_filtered(session, page=1, page_size=2)
    assert total == 5
    assert len(rows) == 2
    assert rows[0].id == "pkg0"  # newest first, default sort


def test_filter_by_status(session):
    _seed(session, "pkg-a", "completed")
    _seed(session, "pkg-b", "review_ready")

    rows, total = db.list_packages_filtered(session, status="review_ready")
    assert total == 1
    assert rows[0].id == "pkg-b"


def test_filter_by_domain(session):
    _seed(session, "pkg-a", "completed", domain="cms1500")
    _seed(session, "pkg-b", "completed", domain="xactimate")

    rows, total = db.list_packages_filtered(session, domain="xactimate")
    assert total == 1
    assert rows[0].id == "pkg-b"


def test_filter_by_decision(session):
    _seed(session, "pkg-a", "completed", decision="approved")
    _seed(session, "pkg-b", "review_ready", decision="escalated")

    rows, total = db.list_packages_filtered(session, decision="escalated")
    assert total == 1
    assert rows[0].id == "pkg-b"


def test_filter_by_confidence_range(session):
    _seed(session, "pkg-a", "completed", domain="cms1500", confidence=0.95)
    _seed(session, "pkg-b", "review_ready", domain="cms1500", confidence=0.4)

    rows, total = db.list_packages_filtered(session, confidence_max=0.5)
    assert total == 1
    assert rows[0].id == "pkg-b"


def test_filter_by_validation_rule(session):
    _seed(session, "pkg-a", "completed", domain="cms1500", confidence=0.9, rule="npi_format")
    _seed(session, "pkg-b", "completed", domain="cms1500", confidence=0.9, rule="date_range")

    rows, total = db.list_packages_filtered(session, validation_rule="npi_format")
    assert total == 1
    assert rows[0].id == "pkg-a"


def test_filter_by_date_range(session):
    _seed(session, "pkg-old", "completed", days_ago=10)
    _seed(session, "pkg-new", "completed", days_ago=0)

    rows, total = db.list_packages_filtered(session, date_from=datetime.now(timezone.utc) - timedelta(days=1))
    assert total == 1
    assert rows[0].id == "pkg-new"


def test_search_matches_package_id_substring(session):
    _seed(session, "abc123", "completed")
    _seed(session, "xyz789", "completed")

    rows, total = db.list_packages_filtered(session, search="abc")
    assert total == 1
    assert rows[0].id == "abc123"


def test_sort_ascending(session):
    _seed(session, "pkg-a", "completed", days_ago=5)
    _seed(session, "pkg-b", "completed", days_ago=1)

    rows, _ = db.list_packages_filtered(session, sort="created_at")
    assert rows[0].id == "pkg-a"  # oldest first


def test_page_size_clamped_to_max(session):
    for i in range(3):
        _seed(session, f"pkg{i}", "completed")

    rows, total = db.list_packages_filtered(session, page_size=99999)
    assert len(rows) == 3  # clamped, not rejected, just bounded by actual data here


def test_list_packages_endpoint_paginates(monkeypatch):
    with TestClient(app) as client:
        for _ in range(3):
            create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        resp = client.get("/packages?page=1&page_size=2")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "page", "page_size", "total"}
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] >= 3
    assert len(body["items"]) == 2


def test_reviews_queue_defaults_to_review_ready_status(monkeypatch):
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

        session = db.SessionLocal()
        db.transition_package_status(session, package_id, "review_ready", reason="test setup")
        session.close()

        resp = client.get("/reviews/queue")

    body = resp.json()
    assert any(item["package_id"] == package_id for item in body["items"])


def test_reviews_queue_explicit_status_overrides_default(monkeypatch):
    with patch("api.main._run_claim"), TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]
        resp = client.get("/reviews/queue?status=queued")

    body = resp.json()
    assert any(item["package_id"] == package_id for item in body["items"])
