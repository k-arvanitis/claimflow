import io
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _make_pdf_bytes() -> bytes:
    # Minimal valid PDF bytes
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"  # noqa: E501


def test_health():
    from api.main import app
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_packages_returns_decision():
    fake_result = {
        "package_dir": "/tmp/test",
        "domain": "cms1500",
        "documents": [{"path": "/tmp/test/claim.pdf", "doc_type": "cms1500", "has_text_layer": True, "scan_quality": None}],
        "extraction_data": {"patient_name": "DOE JOHN"},
        "extraction_fields": [
            {"name": "patient_name", "value": "DOE JOHN", "confidence": 0.95,
             "grounded": True, "valid": True, "field_status": "found", "evidence": None},
        ],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.88,
        "validation_failures": [],
        "policy_answers": [],
        "decision": "approved",
        "review_reasons": [],
        "error": None,
    }

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = fake_result

    with patch("api.main.build_graph", return_value=mock_graph):
        from api.main import app
        from claimflow import db
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            assert response.status_code == 200
            queued = response.json()
            package_id = queued["package_id"]

            result = client.get(f"/packages/{package_id}")

    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "completed"
    assert data["result"]["decision"] == "approved"

    session = db.SessionLocal()
    try:
        assert session.query(db.Document).filter_by(package_id=package_id).count() == 1
        assert (
            session.query(db.ExtractionRun)
            .join(db.Document, db.ExtractionRun.document_id == db.Document.id)
            .filter(db.Document.package_id == package_id)
            .count()
            == 1
        )
        assert (
            session.query(db.ExtractedField)
            .join(db.ExtractionRun, db.ExtractedField.extraction_run_id == db.ExtractionRun.id)
            .join(db.Document, db.ExtractionRun.document_id == db.Document.id)
            .filter(db.Document.package_id == package_id)
            .count()
            == 1
        )
    finally:
        session.close()


def test_get_packages_lists_all():
    from api.main import app
    with TestClient(app) as client:
        pdf_bytes = _make_pdf_bytes()
        with patch("api.main.build_graph", return_value=MagicMock()):
            response = client.get("/packages")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_package_404_for_unknown_id():
    from api.main import app
    with TestClient(app) as client:
        response = client.get("/packages/does-not-exist")
    assert response.status_code == 404


def test_delete_package():
    from api.main import app
    from claimflow import db

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": None, "documents": [], "extraction_fields": [], "extraction_status": None,
        "extraction_overall_confidence": None, "validation_failures": [], "policy_answers": [],
        "decision": None, "review_reasons": [], "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        from api.main import app
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            package_id = response.json()["package_id"]

            delete_response = client.delete(f"/packages/{package_id}")
            assert delete_response.status_code == 200

            get_response = client.get(f"/packages/{package_id}")
            assert get_response.status_code == 404

    session = db.SessionLocal()
    try:
        assert db.get_package(session, package_id) is None
    finally:
        session.close()


def test_reprocess_package():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": None, "documents": [], "extraction_fields": [], "extraction_status": None,
        "extraction_overall_confidence": None, "validation_failures": [], "policy_answers": [],
        "decision": None, "review_reasons": [], "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            package_id = response.json()["package_id"]

            reprocess_response = client.post(f"/packages/{package_id}/process")
            assert reprocess_response.status_code == 200
            assert reprocess_response.json()["status"] == "queued"

    assert mock_graph.invoke.call_count == 2


def test_reprocess_unknown_package_404():
    from api.main import app
    with TestClient(app) as client:
        response = client.post("/packages/does-not-exist/process")
    assert response.status_code == 404


def test_package_status():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": None, "documents": [], "extraction_fields": [], "extraction_status": None,
        "extraction_overall_confidence": None, "validation_failures": [], "policy_answers": [],
        "decision": None, "review_reasons": [], "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            package_id = response.json()["package_id"]

            status_response = client.get(f"/packages/{package_id}/status")

    assert status_response.status_code == 200
    body = status_response.json()
    assert body == {"package_id": package_id, "status": "completed"}


def test_get_documents_for_package():
    from api.main import app
    from claimflow import db

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [{"path": "/tmp/claim.pdf", "doc_type": "cms1500", "has_text_layer": True, "scan_quality": None}],
        "extraction_fields": [], "extraction_status": "pass", "extraction_overall_confidence": 0.9,
        "validation_failures": [], "policy_answers": [], "decision": "approved", "review_reasons": [], "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            package_id = response.json()["package_id"]

            docs_response = client.get(f"/packages/{package_id}/documents")
            assert docs_response.status_code == 200
            docs = docs_response.json()
            assert len(docs) == 1
            document_id = docs[0]["document_id"]

            doc_response = client.get(f"/packages/{package_id}/documents/{document_id}")
            assert doc_response.status_code == 200
            assert doc_response.json()["doc_type"] == "cms1500"

    session = db.SessionLocal()
    try:
        run = db.latest_extraction_run_for_package(session, package_id)
        assert run is not None
    finally:
        session.close()


def test_get_document_404_wrong_package():
    from api.main import app
    with TestClient(app) as client:
        response = client.get("/packages/some-package/documents/does-not-exist")
    assert response.status_code == 404


def test_get_field_evidence_404_for_unknown_field():
    from api.main import app
    with TestClient(app) as client:
        response = client.get("/packages/some-package/fields/999999/evidence")
    assert response.status_code == 404
