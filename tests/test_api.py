from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import io


def _make_pdf_bytes() -> bytes:
    # Minimal valid PDF bytes
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"


def test_health():
    from api.main import app
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_claims_returns_decision():
    fake_result = {
        "package_dir": "/tmp/test",
        "documents": [{"path": "/tmp/test/claim.pdf", "doc_type": "cms1500", "has_text_layer": True}],
        "extraction_data": {"patient_name": "DOE JOHN"},
        "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.88,
        "validation_failures": [],
        "policy_answers": [],
        "decision": "approved",
        "review_reasons": [],
        "error": None,
    }

    with patch("api.main.build_graph") as mock_build:
        mock_app = MagicMock()
        mock_app.invoke.return_value = fake_result
        mock_build.return_value = mock_app

        from api.main import app
        client = TestClient(app)
        pdf_bytes = _make_pdf_bytes()
        response = client.post(
            "/claims",
            files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
        )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "approved"
    assert "validation_failures" in data
