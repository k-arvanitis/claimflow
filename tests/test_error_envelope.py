from fastapi.testclient import TestClient

from api.main import app


def test_404_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "PACKAGE_NOT_FOUND"


def test_422_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/abc/documents/def/pages/not-an-int")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_500_uses_error_envelope(monkeypatch):
    from claimflow import db

    def _boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "list_packages", _boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/packages")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
