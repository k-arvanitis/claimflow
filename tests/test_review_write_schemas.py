from fastapi.testclient import TestClient

from api.main import app


def test_field_review_rejects_invalid_action():
    with TestClient(app) as client:
        resp = client.post("/packages/pkg/fields/1/review", json={"action": "not_a_real_action"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_decision_rejects_invalid_decision():
    with TestClient(app) as client:
        resp = client.post("/packages/pkg/decision", json={"decision": "not_a_real_decision"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
