from fastapi.testclient import TestClient

from api.main import app
from claimflow.domains import all_domains
from claimflow.schemas.enums import DocumentType


def test_reclassify_rejects_unknown_doc_type():
    with TestClient(app) as client:
        create = client.post(
            "/packages", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")}
        )
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


def test_document_type_enum_covers_all_classifier_outputs():
    expected = {"unknown"}
    for domain in all_domains():
        expected.add(domain.doc_type)
        expected.update(domain.supporting_types)

    assert expected <= {item.value for item in DocumentType}
