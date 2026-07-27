from fastapi.testclient import TestClient


def test_doc_intel_output_budget_is_configured():
    from claimflow.config import settings

    assert settings.doc_intel_max_tokens == 8192


def test_get_settings_exposes_no_secrets():
    from api.main import app

    with TestClient(app) as client:
        resp = client.get("/settings")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "confidence_threshold",
        "escalation_threshold",
        "enabled_domains",
        "doc_intel_provider",
        "doc_intel_model",
        "ocr_provider",
        "ocr_fallback_providers",
        "qdrant_url",
        "qdrant_collection",
        "langfuse_enabled",
        "anthropic_api_key_configured",
    }
    assert "cms1500" in body["enabled_domains"]
    assert isinstance(body["anthropic_api_key_configured"], bool)
    # never leak the actual key material
    assert "anthropic_api_key" not in body
