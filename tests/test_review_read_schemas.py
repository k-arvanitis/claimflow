from fastapi.testclient import TestClient

from api.main import app


def test_evidence_404_uses_error_envelope():
    with TestClient(app) as client:
        resp = client.get("/packages/pkg/fields/999999/evidence")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FIELD_NOT_FOUND"


def test_reviews_queue_shape():
    with TestClient(app) as client:
        resp = client.get("/reviews/queue")
    assert resp.status_code == 200
    assert resp.json() == []
