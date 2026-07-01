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


def test_extract_node_calls_doc_intel(tmp_path):
    """Extract node calls doc-intel extract() with CMS-1500 spec and stores result."""
    from unittest.mock import MagicMock, patch
    from claimflow.state import ClaimState

    fake_result = MagicMock()
    fake_result.data = {"patient_name": "DOE JOHN", "insurance_id": "INS123"}
    fake_result.fields = []
    fake_result.overall_confidence = 0.88
    fake_result.status = "pass"

    claim_pdf = tmp_path / "claim.pdf"
    claim_pdf.write_bytes(b"placeholder")

    state: ClaimState = {
        "package_dir": str(tmp_path),
        "documents": [{"path": str(claim_pdf), "doc_type": "cms1500", "has_text_layer": True}],
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

    with patch("claimflow.nodes.extract.extract", return_value=fake_result) as mock_extract:
        from claimflow.nodes.extract import extract_node
        result = extract_node(state)

    mock_extract.assert_called_once_with(str(claim_pdf), mock_extract.call_args[0][1])
    assert result["extraction_data"]["patient_name"] == "DOE JOHN"
    assert result["extraction_overall_confidence"] == 0.88
    assert result["extraction_status"] == "pass"
