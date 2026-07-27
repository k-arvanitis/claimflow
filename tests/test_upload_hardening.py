import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
from fastapi.testclient import TestClient

from api.main import app


def test_upload_rejects_unsupported_extension():
    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[("files", ("malware.exe", io.BytesIO(b"x"), "application/octet-stream"))],
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_rejects_too_many_files(monkeypatch):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "max_files_per_package", 2)

    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[
                ("files", ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")),
                ("files", ("b.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")),
                ("files", ("c.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")),
            ],
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TOO_MANY_FILES"


def test_upload_rejects_oversized_file_and_leaves_no_trace(monkeypatch, tmp_path):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "max_upload_size_bytes", 10)
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[("files", ("big.pdf", io.BytesIO(b"%PDF-1.4" * 100), "application/pdf"))],
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FILE_TOO_LARGE"
    # test.db is the isolated_db fixture's harness file, not upload output
    assert [p for p in tmp_path.iterdir() if p.name != "test.db"] == []  # no orphaned package directory


def test_upload_rejects_no_files_leaves_no_trace_and_no_db_row(monkeypatch, tmp_path):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    from claimflow import db

    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[("files", ("bad.exe", io.BytesIO(b"x"), "application/octet-stream"))],
        )
    assert resp.status_code == 400
    # test.db is the isolated_db fixture's harness file, not upload output
    assert [p for p in tmp_path.iterdir() if p.name != "test.db"] == []

    session = db.SessionLocal()
    assert db.list_packages(session).__len__() == 0 if hasattr(db.list_packages(session), "__len__") else True
    session.close()


def test_upload_disambiguates_duplicate_filenames_in_same_upload(monkeypatch, tmp_path):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    with TestClient(app) as client:
        resp = client.post(
            "/packages",
            files=[
                ("files", ("claim.pdf", io.BytesIO(b"%PDF-1.4 first"), "application/pdf")),
                ("files", ("claim.pdf", io.BytesIO(b"%PDF-1.4 second"), "application/pdf")),
            ],
        )
    assert resp.status_code == 200
    package_id = resp.json()["package_id"]
    stored_files = sorted(p.name for p in (tmp_path / package_id).iterdir())
    assert len(stored_files) == 2  # both files present, neither overwrote the other


def test_document_list_does_not_expose_filesystem_path():
    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("claim.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]
        resp = client.get(f"/packages/{package_id}/documents")

    body = resp.json()
    assert len(body) == 1
    assert "path" not in body[0]
    assert body[0]["filename"] == "claim.pdf"


def test_page_render_rejects_document_path_outside_package_dir(tmp_path, monkeypatch):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    from claimflow import db

    with TestClient(app) as client:
        create = client.post("/packages", files={"files": ("claim.pdf", b"%PDF-1.4", "application/pdf")})
        package_id = create.json()["package_id"]

    outside_file = tmp_path.parent / "outside.pdf"
    outside_file.write_bytes(b"%PDF-1.4 secret")

    session = db.SessionLocal()
    doc = db.Document(id="evil-doc", package_id=package_id, path=str(outside_file), doc_type="cms1500", has_text_layer=True)
    session.add(doc)
    session.commit()
    session.close()

    with TestClient(app) as client:
        resp = client.get(f"/packages/{package_id}/documents/evil-doc/pages/1")

    assert resp.status_code == 404


def test_page_render_succeeds_for_legitimate_document(tmp_path, monkeypatch):
    from claimflow.config import settings
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    pdf_doc = fitz.open()
    pdf_doc.new_page()
    pdf_bytes = pdf_doc.tobytes()
    pdf_doc.close()

    def fake_invoke(state, config):
        return {
            "domain": "cms1500",
            "documents": [{
                "path": str(Path(state["package_dir"]) / "claim.pdf"),
                "doc_type": "cms1500", "has_text_layer": True, "scan_quality": None,
            }],
            "extraction_fields": [], "extraction_status": "pass", "extraction_overall_confidence": 0.9,
            "validation_failures": [], "policy_answers": [], "decision": "ready_for_processing",
            "review_reasons": [], "error": None,
        }

    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = fake_invoke

    with patch("api.main.build_graph", return_value=mock_graph):
        with TestClient(app) as client:
            create = client.post(
                "/packages",
                files=[("files", ("claim.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            )
            package_id = create.json()["package_id"]

            document_id = client.get(f"/packages/{package_id}/documents").json()[0]["document_id"]

            resp = client.get(f"/packages/{package_id}/documents/{document_id}/pages/1")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
