from fastapi.testclient import TestClient

from api.main import app


def test_export_404_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/does-not-exist/export")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PACKAGE_NOT_FOUND"


def test_audit_trail_shape():
    with TestClient(app) as client:
        resp = client.get("/packages/does-not-exist/audit")
    assert resp.status_code == 200
    assert resp.json() == []
