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
            page.get_text.return_value = "DISCHARGE SUMMARY\nPatient: John Doe\nDischarge diagnosis and instructions follow below in full detail."
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

    other_doc = next(d for d in docs if d["path"] != claim_doc["path"])
    assert other_doc["doc_type"] == "discharge_summary"


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
        "domain": "cms1500",
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

    assert mock_extract.called
    assert result["extraction_data"]["patient_name"] == "DOE JOHN"
    assert result["extraction_overall_confidence"] == 0.88
    assert result["extraction_status"] == "pass"


def test_review_node_approves_clean_claim():
    from claimflow.nodes.review import review_node
    from claimflow.state import ClaimState

    state: ClaimState = {
        "package_dir": "/tmp", "documents": [],
        "extraction_data": {}, "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.90,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None, "review_reasons": [], "error": None,
    }
    result = review_node(state)
    assert result["decision"] == "approved"
    assert result["review_reasons"] == []


def test_review_node_flags_validation_failures():
    from claimflow.nodes.review import review_node
    from claimflow.state import ClaimState, ValidationFailure

    state: ClaimState = {
        "package_dir": "/tmp", "documents": [],
        "extraction_data": {}, "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.85,
        "validation_failures": [
            ValidationFailure(field="total_charge", rule="arithmetic", reason="mismatch")
        ],
        "policy_answers": [],
        "decision": None, "review_reasons": [], "error": None,
    }
    result = review_node(state)
    assert result["decision"] == "flagged"
    assert len(result["review_reasons"]) > 0


def test_review_node_escalates_low_confidence():
    from claimflow.nodes.review import review_node
    from claimflow.state import ClaimState

    state: ClaimState = {
        "package_dir": "/tmp", "documents": [],
        "extraction_data": {}, "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.40,  # below escalation_threshold
        "validation_failures": [],
        "policy_answers": [],
        "decision": None, "review_reasons": [], "error": None,
    }
    result = review_node(state)
    assert result["decision"] == "escalated"


def test_graph_runs_end_to_end(tmp_path):
    """Graph executes all nodes and produces a decision."""
    from unittest.mock import MagicMock, patch

    claim_pdf = tmp_path / "claim.pdf"
    claim_pdf.write_bytes(b"placeholder")

    def mock_fitz_open(path):
        doc = MagicMock()
        page = MagicMock()
        page.get_text.return_value = "HEALTH INSURANCE CLAIM FORM CMS-1500\nBox 1a: INS123"
        doc.__iter__ = lambda s: iter([page])
        doc.__len__ = lambda s: 1
        return doc

    fake_extraction = MagicMock()
    fake_extraction.data = {
        "insurance_id": "INS123", "patient_name": "DOE JOHN",
        "patient_dob": "01011980", "billing_provider_npi": "1487293650",
        "diagnosis_codes": ["J06.9"],
        "service_lines": [{"cpt_code": "99213", "date_of_service": "01012026", "charges": "150.00", "units": 1, "place_of_service": "11", "diagnosis_pointer": "A"}],  # noqa: E501
        "total_charge": "150.00", "signature_on_file": True,
    }
    fake_extraction.fields = []
    fake_extraction.overall_confidence = 0.88
    fake_extraction.status = "pass"

    with patch("claimflow.nodes.ingest.fitz.open", side_effect=mock_fitz_open), \
         patch("claimflow.nodes.extract.extract", return_value=fake_extraction), \
         patch("claimflow.lookups.icd10.is_valid_icd10", return_value=True), \
         patch("claimflow.lookups.cpt.is_valid_cpt", return_value=True):
        from claimflow.graph import build_graph
        app = build_graph()
        result = app.invoke({"package_dir": str(tmp_path)}, config={"configurable": {"thread_id": "test"}})

    assert result["decision"] in ("approved", "flagged", "escalated")
    assert result["documents"]


def test_ingest_node_handles_docx_and_image(tmp_path):
    """Ingest node converts DOCX to PDF and opens images natively, classifying both."""
    import docx
    from PIL import Image

    pkg = tmp_path / "package"
    pkg.mkdir()

    doc = docx.Document()
    doc.add_paragraph("SBA LOAN APPLICATION\nBusiness loan application for Acme Corp.")
    doc.save(str(pkg / "application.docx"))

    Image.new("RGB", (100, 100), color="white").save(pkg / "photo.png")

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
    docx_doc = next(d for d in docs if d["path"].endswith(".pdf"))
    assert docx_doc["doc_type"] == "loan"
    assert result["domain"] == "loan"

    image_doc = next(d for d in docs if d["path"].endswith(".png"))
    assert image_doc["has_text_layer"] is False


def test_retrieve_node_skipped_when_no_failures():
    """Retrieve node returns empty answers when there are no failures to look up."""
    from claimflow.nodes.retrieve import retrieve_node
    from claimflow.state import ClaimState

    state: ClaimState = {
        "package_dir": "/tmp", "documents": [],
        "extraction_data": {}, "extraction_fields": [],
        "extraction_status": "pass", "extraction_overall_confidence": 0.9,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None, "review_reasons": [], "error": None,
    }
    result = retrieve_node(state)
    assert result["policy_answers"] == []
