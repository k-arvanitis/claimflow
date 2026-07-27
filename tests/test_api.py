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


def test_cors_allows_frontend_origin():
    from api.main import app

    client = TestClient(app)
    response = client.get("/health", headers={"Origin": "http://localhost:3001"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3001"


def test_post_packages_returns_decision():
    fake_result = {
        "package_dir": "/tmp/test",
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/test/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
            }
        ],
        "extraction_data": {"patient_name": "DOE JOHN"},
        "extraction_fields": [
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
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            assert response.status_code == 200
            queued = response.json()
            assert queued["status"] == "processing"
            package_id = queued["package_id"]

            result = client.get(f"/packages/{package_id}")

    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "completed"
    assert data["result"]["decision"] == "approved"
    assert data["result"]["documents"] == [
        {
            "filename": "claim.pdf",
            "doc_type": "cms1500",
            "has_text_layer": True,
            "scan_quality": None,
            "classification_reason": None,
        }
    ]
    assert "path" not in data["result"]["documents"][0]
    assert data["domain"] == "cms1500"
    assert data["overall_confidence"] == 0.88
    assert data["document_count"] == 1
    assert data["validation_failure_count"] == 0
    assert (
        data["decision"] == "approved"
    )  # persist_extraction_result records a Decision row on graph completion
    assert data["review_reasons"] == []
    assert data["created_at"] and data["updated_at"]

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
            .join(
                db.ExtractionRun,
                db.ExtractedField.extraction_run_id == db.ExtractionRun.id,
            )
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
        with patch("api.main.build_graph", return_value=MagicMock()):
            response = client.get("/packages")
    assert response.status_code == 200
    assert isinstance(response.json()["items"], list)


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
        "domain": None,
        "documents": [],
        "extraction_fields": [],
        "extraction_status": None,
        "extraction_overall_confidence": None,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        from api.main import app

        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
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
        "domain": None,
        "documents": [],
        "extraction_fields": [],
        "extraction_status": None,
        "extraction_overall_confidence": None,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            reprocess_response = client.post(f"/packages/{package_id}/process")
            assert reprocess_response.status_code == 200
            assert reprocess_response.json()["status"] == "processing"

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
        "domain": None,
        "documents": [],
        "extraction_fields": [],
        "extraction_status": None,
        "extraction_overall_confidence": None,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            status_response = client.get(f"/packages/{package_id}/status")

    assert status_response.status_code == 200
    body = status_response.json()
    assert body == {"package_id": package_id, "status": "review_ready"}


def test_get_documents_for_package():
    from api.main import app
    from claimflow import db

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
            }
        ],
        "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.9,
        "validation_failures": [],
        "policy_answers": [],
        "decision": "approved",
        "review_reasons": [],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
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


def test_reviews_queue_lists_flagged_packages():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
            }
        ],
        "extraction_fields": [],
        "extraction_status": "review",
        "extraction_overall_confidence": 0.5,
        "validation_failures": [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "bad code"}
        ],
        "policy_answers": [],
        "decision": "flagged",
        "review_reasons": ["bad code"],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            queue_response = client.get("/reviews/queue")

    assert queue_response.status_code == 200
    queue_ids = {item["package_id"] for item in queue_response.json()["items"]}
    assert package_id in queue_ids


def test_package_review_view():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
            }
        ],
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
        "extraction_status": "review",
        "extraction_overall_confidence": 0.5,
        "validation_failures": [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "bad code"}
        ],
        "policy_answers": [],
        "decision": "flagged",
        "review_reasons": ["bad code"],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            review_response = client.get(f"/packages/{package_id}/review")

    assert review_response.status_code == 200
    body = review_response.json()
    assert len(body["fields"]) == 1
    assert body["fields"][0]["name"] == "diagnosis_codes"
    assert len(body["validation_failures"]) == 1


def test_submit_field_review():
    from api.main import app
    from claimflow import db

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
            }
        ],
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
        "extraction_status": "review",
        "extraction_overall_confidence": 0.5,
        "validation_failures": [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "bad code"}
        ],
        "policy_answers": [],
        "decision": "flagged",
        "review_reasons": ["bad code"],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            review_view = client.get(f"/packages/{package_id}/review").json()
            field_id = review_view["fields"][0]["field_id"]

            action_response = client.post(
                f"/packages/{package_id}/fields/{field_id}/review",
                json={
                    "action": "edit",
                    "corrected_value": ["J06.9"],
                    "reviewer": "jane",
                    "note": "fixed typo",
                },
            )

    assert action_response.status_code == 200
    body = action_response.json()
    assert body["action"] == "edit"

    session = db.SessionLocal()
    try:
        run = session.get(db.ExtractedField, field_id).extraction_run_id
        assert (
            session.query(db.ReviewAction)
            .filter_by(extraction_run_id=run, field_name="diagnosis_codes")
            .count()
            == 1
        )
    finally:
        session.close()


def test_field_review_404_for_wrong_package():
    from api.main import app

    with TestClient(app) as client:
        response = client.post(
            "/packages/wrong-package/fields/999999/review",
            json={"action": "approve"},
        )
    assert response.status_code == 404


def test_validation_rerun():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
            }
        ],
        "extraction_data": {"diagnosis_codes": ["XXXXX"], "total_charge": 100.0},
        "extraction_fields": [],
        "extraction_status": "review",
        "extraction_overall_confidence": 0.5,
        "validation_failures": [],
        "policy_answers": [],
        "decision": "flagged",
        "review_reasons": [],
        "error": None,
    }
    with (
        patch("api.main.build_graph", return_value=mock_graph),
        patch("claimflow.review.rerun_validation", return_value=[]) as mock_rerun,
    ):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            rerun_response = client.post(
                f"/packages/{package_id}/validation/re-run",
                json={"corrected_fields": {"diagnosis_codes": ["J06.9"]}},
            )

    assert rerun_response.status_code == 200
    assert rerun_response.json()["validation_failures"] == []
    assert mock_rerun.called


def test_rerun_validation_endpoint_persists_results():
    from api.main import app
    from claimflow import db

    with patch("api.main.build_graph", return_value=MagicMock()):
        with TestClient(app) as client:
            create = client.post(
                "/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")}
            )
            package_id = create.json()["package_id"]

            session = db.SessionLocal()
            db.update_package_status(
                session,
                package_id,
                "review_ready",
                result={
                    "domain": "cms1500",
                    "extraction_data": {"patient_name": "DOE JOHN"},
                },
            )
            session.close()

            resp = client.post(
                f"/packages/{package_id}/validation/re-run",
                json={"corrected_fields": {"patient_name": "DOE JON"}},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert "decision" in body
    assert "decision_changed" in body


def test_submit_decision():
    from api.main import app
    from claimflow import db

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": None,
        "documents": [],
        "extraction_fields": [],
        "extraction_status": None,
        "extraction_overall_confidence": None,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            decision_response = client.post(
                f"/packages/{package_id}/decision",
                json={"decision": "approved", "review_reasons": []},
            )

    assert decision_response.status_code == 200
    assert decision_response.json()["decision"] == "approved"

    session = db.SessionLocal()
    try:
        latest = db.latest_decision_for_package(session, package_id)
        assert latest.decision == "approved"
    finally:
        session.close()


def test_policy_evidence_and_audit_endpoints():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
            }
        ],
        "extraction_fields": [],
        "extraction_status": "review",
        "extraction_overall_confidence": 0.5,
        "validation_failures": [
            {"field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "bad code"}
        ],
        "policy_answers": [
            {
                "question": "Is XXXXX billable?",
                "answer": "No.",
                "citations": ["policy excerpt [1]"],
            }
        ],
        "decision": "flagged",
        "review_reasons": ["bad code"],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            evidence_response = client.get(f"/packages/{package_id}/policy-evidence")
            audit_response = client.get(f"/packages/{package_id}/audit")
            export_response = client.get(f"/packages/{package_id}/export")

    assert evidence_response.status_code == 200
    assert len(evidence_response.json()) == 1
    assert evidence_response.json()[0]["question"] == "Is XXXXX billable?"

    assert audit_response.status_code == 200
    audit_actions = {entry["action"] for entry in audit_response.json()}
    assert "upload" in audit_actions

    assert export_response.status_code == 200
    export_body = export_response.json()
    assert export_body["package_id"] == package_id
    assert export_body["decision"] == "flagged"


def test_export_404_for_unknown_package():
    from api.main import app

    with TestClient(app) as client:
        response = client.get("/packages/does-not-exist/export")
    assert response.status_code == 404


def test_reclassify_document():
    from api.main import app
    from claimflow import db

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": None,
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "unknown",
                "has_text_layer": True,
                "scan_quality": None,
                "classification_reason": None,
            }
        ],
        "extraction_fields": [],
        "extraction_status": None,
        "extraction_overall_confidence": None,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            docs = client.get(f"/packages/{package_id}/documents").json()
            document_id = docs[0]["document_id"]

            reclassify_response = client.post(
                f"/packages/{package_id}/documents/{document_id}/reclassify",
                json={"doc_type": "cms1500", "reviewer": "jane"},
            )

    assert reclassify_response.status_code == 200
    body = reclassify_response.json()
    assert body["doc_type"] == "cms1500"
    assert body["manually_overridden"] is True

    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        assert doc.doc_type == "cms1500"
        assert doc.classification_reason == "manual override"
        assert doc.manually_overridden is True
    finally:
        session.close()


def test_reclassify_document_404_for_wrong_package():
    from api.main import app

    with TestClient(app) as client:
        response = client.post(
            "/packages/wrong-package/documents/does-not-exist/reclassify",
            json={"doc_type": "cms1500"},
        )
    assert response.status_code == 404


def test_reprocess_passes_overrides_to_graph():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": None,
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "unknown",
                "has_text_layer": True,
                "scan_quality": None,
                "classification_reason": None,
            }
        ],
        "extraction_fields": [],
        "extraction_status": None,
        "extraction_overall_confidence": None,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            docs = client.get(f"/packages/{package_id}/documents").json()
            document_id = docs[0]["document_id"]
            client.post(
                f"/packages/{package_id}/documents/{document_id}/reclassify",
                json={"doc_type": "cms1500"},
            )

            client.post(f"/packages/{package_id}/process")

    assert mock_graph.invoke.call_count == 2
    second_call_state = mock_graph.invoke.call_args_list[1][0][0]
    assert second_call_state["doc_type_overrides"] == {"claim.pdf": "cms1500"}


def test_list_documents_includes_classification_metadata():
    from api.main import app

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "domain": "cms1500",
        "documents": [
            {
                "path": "/tmp/claim.pdf",
                "doc_type": "cms1500",
                "has_text_layer": True,
                "scan_quality": None,
                "classification_reason": "matched domain keyword 'cms-1500' for cms1500",
            }
        ],
        "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.9,
        "validation_failures": [],
        "policy_answers": [],
        "decision": "approved",
        "review_reasons": [],
        "error": None,
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            pdf_bytes = _make_pdf_bytes()
            response = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                ],
            )
            package_id = response.json()["package_id"]

            docs = client.get(f"/packages/{package_id}/documents").json()

    assert (
        docs[0]["classification_reason"]
        == "matched domain keyword 'cms-1500' for cms1500"
    )
    assert docs[0]["manually_overridden"] is False


def test_dashboard_summary_endpoint():
    from api.main import app

    with TestClient(app) as client:
        resp = client.get("/dashboard/summary")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "total_packages",
        "processing",
        "awaiting_review",
        "approved",
        "flagged",
        "escalated",
        "processing_errors",
        "straight_through_rate",
        "top_validation_failures",
    }
