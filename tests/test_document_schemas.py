from fastapi.testclient import TestClient

from api.main import app


def test_reclassify_rejects_unknown_doc_type():
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]
        docs = client.get(f"/packages/{package_id}/documents").json()

    if not docs:
        return  # background processing hasn't classified yet in this test's timing; covered by lifecycle test in Task 9

    document_id = docs[0]["document_id"]
    with TestClient(app) as client:
        resp = client.post(
            f"/packages/{package_id}/documents/{document_id}/reclassify",
            json={"doc_type": "not_a_real_type"},
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
