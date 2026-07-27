from fastapi.testclient import TestClient

from api.main import app

EXPECTED_ROUTES = {
    ("GET", "/health"),
    ("GET", "/dashboard/summary"),
    ("GET", "/settings"),
    ("POST", "/packages"),
    ("GET", "/packages"),
    ("GET", "/packages/{package_id}"),
    ("DELETE", "/packages/{package_id}"),
    ("POST", "/packages/{package_id}/process"),
    ("GET", "/packages/{package_id}/status"),
    ("GET", "/packages/{package_id}/documents"),
    ("GET", "/packages/{package_id}/documents/{document_id}"),
    ("POST", "/packages/{package_id}/documents/{document_id}/reclassify"),
    ("GET", "/packages/{package_id}/documents/{document_id}/pages/{page}"),
    ("GET", "/packages/{package_id}/fields/{field_id}/evidence"),
    ("GET", "/reviews/queue"),
    ("GET", "/packages/{package_id}/review"),
    ("POST", "/packages/{package_id}/fields/{field_id}/review"),
    ("POST", "/packages/{package_id}/validation/re-run"),
    ("POST", "/packages/{package_id}/decision"),
    ("GET", "/packages/{package_id}/policy-evidence"),
    ("GET", "/packages/{package_id}/audit"),
    ("GET", "/packages/{package_id}/export"),
    ("GET", "/domain-packs"),
    ("GET", "/domain-packs/{key}"),
}


def test_openapi_schema_has_every_route_with_response_model():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    found = set()
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            found.add((method.upper(), path))
            if path == "/health":
                continue
            responses = operation["responses"]
            success = responses.get("200") or responses.get("201")
            assert "content" in success, f"{method.upper()} {path} has no typed 200 response"
            assert "404" in responses or "422" in responses or method.upper() == "GET"

    assert found == EXPECTED_ROUTES


def test_openapi_error_responses_reference_error_envelope():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    assert "ErrorEnvelope" in schema["components"]["schemas"]
