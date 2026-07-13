from fastapi.testclient import TestClient

from api.main import app


def test_list_packages_response_shape():
    with TestClient(app) as client:
        resp = client.get("/packages")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_package_status_field_is_enum_value():
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert create.status_code == 200
    body = create.json()
    assert body["status"] in ("queued", "processing", "completed", "failed")
    assert set(body.keys()) == {"package_id", "status"}
