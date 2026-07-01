from unittest.mock import MagicMock, patch


def test_ingest_node_classifies_cms1500(tmp_path):
    """Ingest node identifies the claim form and supporting docs."""
    pkg = tmp_path / "package"
    pkg.mkdir()
    claim_pdf = pkg / "claim.pdf"
    other_pdf = pkg / "discharge.pdf"
    claim_pdf.write_bytes(b"placeholder")
    other_pdf.write_bytes(b"placeholder")

    def mock_open(path):
        doc = MagicMock()
        page = MagicMock()
        if "claim" in str(path):
            page.get_text.return_value = "HEALTH INSURANCE CLAIM FORM CMS-1500\nBox 1a: INS123"
        else:
            page.get_text.return_value = "DISCHARGE SUMMARY\nPatient: John Doe"
        doc.__iter__ = lambda s: iter([page])
        doc.__len__ = lambda s: 1
        return doc

    with patch("claimflow.nodes.ingest.fitz.open", side_effect=mock_open):
        from claimflow.nodes.ingest import ingest_node
        from claimflow.state import ClaimState

        state: ClaimState = {
            "package_dir": str(pkg),
            "documents": [],
            "extraction_data": None,
            "extraction_fields": None,
            "extraction_status": None,
            "extraction_overall_confidence": None,
            "validation_failures": [],
            "policy_answers": [],
            "decision": None,
            "review_reasons": [],
            "error": None,
        }
        result = ingest_node(state)

    docs = result["documents"]
    assert len(docs) == 2
    claim_doc = next(d for d in docs if d["doc_type"] == "cms1500")
    assert claim_doc["has_text_layer"] is True
