"""One connected walk through the full package lifecycle, using a single
package_id throughout — the per-endpoint tests elsewhere in this suite already
cover isolated behavior (retry, duplicate /process, invalid ids, path
traversal, etc); this file proves the pieces actually chain together."""

import io
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from claimflow import db

_PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"  # noqa: E501


def test_full_package_lifecycle():
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
                "confidence": 0.6,
                "grounded": True,
                "valid": True,
                "field_status": "review",
                "evidence": None,
            },
        ],
        "extraction_status": "review",
        "extraction_overall_confidence": 0.6,
        "validation_failures": [
            {"field": "patient_dob", "rule": "mandatory", "reason": "missing"}
        ],
        "policy_answers": [],
        "decision": "needs_review",
        "review_reasons": ["low confidence"],
        "error": None,
    }
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = fake_result

    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            # upload -> processing kicks off automatically
            upload = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(_PDF_BYTES), "application/pdf"))
                ],
            )
            assert upload.status_code == 200
            package_id = upload.json()["package_id"]

            # package landed in review_ready (flagged decision), not completed
            pkg = client.get(f"/packages/{package_id}")
            assert pkg.status_code == 200
            assert pkg.json()["status"] == "review_ready"

            # classified documents visible
            docs = client.get(f"/packages/{package_id}/documents")
            assert docs.status_code == 200
            assert len(docs.json()) == 1

            # extracted fields + validation failure visible in the review queue
            review = client.get(f"/packages/{package_id}/review")
            assert review.status_code == 200
            review_body = review.json()
            assert len(review_body["fields"]) == 1
            assert len(review_body["validation_failures"]) == 1
            field_id = review_body["fields"][0]["field_id"]

            # field evidence endpoint resolves for that field
            evidence = client.get(f"/packages/{package_id}/fields/{field_id}/evidence")
            assert evidence.status_code == 200

            # package shows up in the reviews queue
            queue = client.get("/reviews/queue")
            assert any(
                item["package_id"] == package_id for item in queue.json()["items"]
            )

            # reviewer corrects the field
            field_review = client.post(
                f"/packages/{package_id}/fields/{field_id}/review",
                json={
                    "action": "edit",
                    "corrected_value": "DOE JON",
                    "reviewer": "alice",
                },
            )
            assert field_review.status_code == 200

            # validation re-run with the correction persists and reports a decision
            rerun = client.post(
                f"/packages/{package_id}/validation/re-run",
                json={"corrected_fields": {"patient_name": "DOE JON"}},
            )
            assert rerun.status_code == 200
            assert "decision" in rerun.json()

            after_rerun = client.get(f"/packages/{package_id}").json()
            assert after_rerun["decision"] == rerun.json()["decision"]
            assert (
                after_rerun["result"]["validation_failures"]
                == rerun.json()["validation_failures"]
            )

            # reviewer records the final decision
            decision = client.post(
                f"/packages/{package_id}/decision",
                json={"decision": "ready_for_processing"},
            )
            assert decision.status_code == 200
            assert decision.json()["decision"] == "ready_for_processing"
            assert client.get(f"/packages/{package_id}").json()["status"] == "completed"

            # audit trail recorded the whole journey
            audit = client.get(f"/packages/{package_id}/audit")
            assert audit.status_code == 200
            actions = {entry["action"] for entry in audit.json()}
            assert {
                "upload",
                "status_transition",
                "review_edit",
                "validation_rerun",
                "decision",
            } <= actions

            # export reflects the finalized package
            export = client.get(f"/packages/{package_id}/export")
            assert export.status_code == 200
            export_body = export.json()
            assert export_body["decision"] == "ready_for_processing"
            patient_name = next(
                field
                for field in export_body["extraction_fields"]
                if field["name"] == "patient_name"
            )
            assert patient_name["value"] == "DOE JOHN"
            assert patient_name["final_value"] == "DOE JON"
            assert patient_name["reviewer_action"] == "edit"

            # delete removes it
            delete = client.delete(f"/packages/{package_id}")
            assert delete.status_code == 200
            assert client.get(f"/packages/{package_id}").status_code == 404

    session = db.SessionLocal()
    try:
        assert db.get_package(session, package_id) is None
    finally:
        session.close()


def test_rerun_validation_reports_decision_changed_with_new_labels():
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
        "extraction_data": {"billing_provider_npi": "1234567890"},
        "extraction_fields": [
            {
                "name": "billing_provider_npi",
                "value": "1234567890",
                "confidence": 0.6,
                "grounded": True,
                "valid": False,
                "field_status": "review",
                "evidence": None,
            },
        ],
        "extraction_status": "review",
        "extraction_overall_confidence": 0.6,
        "validation_failures": [
            {
                "field": "billing_provider_npi",
                "rule": "npi_checksum",
                "reason": "invalid checksum",
            }
        ],
        "policy_answers": [],
        "decision": "needs_review",
        "review_reasons": ["invalid NPI"],
        "error": None,
    }
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = fake_result

    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            upload = client.post(
                "/packages",
                files=[
                    ("files", ("claim.pdf", io.BytesIO(_PDF_BYTES), "application/pdf"))
                ],
            )
            assert upload.status_code == 200
            package_id = upload.json()["package_id"]

            status = client.get(f"/packages/{package_id}")
            assert status.json()["status"] == "review_ready"

            rerun = client.post(
                f"/packages/{package_id}/validation/re-run",
                json={"corrected_fields": {"billing_provider_npi": "1234567893"}},
            )
            assert rerun.status_code == 200
            body = rerun.json()
            assert body["decision"] in (
                "ready_for_processing",
                "needs_review",
                "blocked_or_incomplete",
            )
            assert isinstance(body["decision_changed"], bool)
