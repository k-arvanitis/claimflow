"""Tests for src/claimflow/policy_index.py."""

from unittest.mock import MagicMock, patch

import pytest

from claimflow import policy_index


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(policy_index, "POLICIES_DIR", tmp_path)
    monkeypatch.setattr(policy_index, "META_PATH", tmp_path / "_meta.json")


def _fake_pdf_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Net income may not exceed gross revenue.")
    return doc.tobytes()


def test_save_and_list_policy_file(tmp_path):
    policy_index.save_policy_file(
        "new_loan_rule.pdf", _fake_pdf_bytes(), "loan", "synthetic"
    )

    files = policy_index.list_policy_files(tmp_path)
    assert len(files) == 1
    assert files[0]["filename"] == "new_loan_rule.pdf"
    assert files[0]["domain"] == "loan"
    assert files[0]["authority"] == "synthetic"
    assert files[0]["size_bytes"] > 0


def test_delete_policy_file(tmp_path):
    policy_index.save_policy_file("temp.pdf", _fake_pdf_bytes(), "health", "synthetic")
    assert policy_index.delete_policy_file("temp.pdf") is True
    assert policy_index.list_policy_files(tmp_path) == []
    assert policy_index.delete_policy_file("temp.pdf") is False


def test_delete_policy_file_stays_within_policies_dir(tmp_path):
    outside = tmp_path.parent / "escaped.pdf"
    outside.write_bytes(_fake_pdf_bytes())
    try:
        # Path(...).name discards directory components, so this resolves to
        # policies_dir/escaped.pdf (which doesn't exist), never the real file above.
        assert policy_index.delete_policy_file("../escaped.pdf") is False
        assert outside.exists()
    finally:
        outside.unlink(missing_ok=True)


def test_domain_falls_back_to_filename_heuristic_when_no_metadata(tmp_path):
    (tmp_path / "property_endorsement.pdf").write_bytes(_fake_pdf_bytes())
    files = policy_index.list_policy_files(tmp_path)
    assert files[0]["domain"] == "property"
    assert files[0]["authority"] == "synthetic"


def test_reindex_tags_chunks_with_resolved_domain_and_authority(tmp_path):
    policy_index.save_policy_file(
        "cms_rule.pdf", _fake_pdf_bytes(), "health", "official_cms"
    )

    fake_client = MagicMock()
    fake_client.get_collections.return_value = MagicMock(collections=[])
    with patch("qdrant_client.QdrantClient", return_value=fake_client):
        count = policy_index.reindex(tmp_path)

    assert count > 0
    fake_client.add.assert_called_once()
    metadata = fake_client.add.call_args.kwargs["metadata"]
    assert all(
        m["domain"] == "health" and m["authority"] == "official_cms" for m in metadata
    )


def test_reindex_returns_zero_when_no_pdfs(tmp_path):
    count = policy_index.reindex(tmp_path)
    assert count == 0
