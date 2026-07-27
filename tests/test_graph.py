from unittest.mock import MagicMock, patch


def test_ingest_node_uses_build_artifact(tmp_path):
    """Ingest node delegates OCR/text-layer detection to doc-intel's build_artifact,
    not its own fitz call."""

    pkg = tmp_path / "package"
    pkg.mkdir()
    claim_pdf = pkg / "claim.pdf"
    claim_pdf.write_bytes(b"placeholder")

    fake_page = MagicMock()
    fake_page.text = "HEALTH INSURANCE CLAIM FORM CMS-1500\nBox 1a: INS123"
    fake_page.native_text_available = True
    fake_page.ocr_used = False
    fake_artifact = MagicMock()
    fake_artifact.pages = [fake_page]

    with patch(
        "claimflow.nodes.ingest.build_artifact", return_value=fake_artifact
    ) as mock_build:
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

    assert mock_build.called
    docs = result["documents"]
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "cms1500"
    assert docs[0]["has_text_layer"] is True
    assert docs[0]["scan_quality"] is None


def test_ingest_node_classifies_cms1500(tmp_path):
    """Ingest node identifies the claim form and supporting docs."""

    pkg = tmp_path / "package"
    pkg.mkdir()
    claim_pdf = pkg / "claim.pdf"
    other_pdf = pkg / "discharge.pdf"
    claim_pdf.write_bytes(b"placeholder")
    other_pdf.write_bytes(b"placeholder")

    def mock_build_artifact(path):
        page = MagicMock()
        page.native_text_available = True
        page.ocr_used = False
        if "claim" in str(path):
            page.text = "HEALTH INSURANCE CLAIM FORM CMS-1500\nBox 1a: INS123"
        else:
            page.text = "DISCHARGE SUMMARY\nPatient: John Doe\nDischarge diagnosis and instructions follow below in full detail."  # noqa: E501
        artifact = MagicMock()
        artifact.pages = [page]
        return artifact

    with patch(
        "claimflow.nodes.ingest.build_artifact", side_effect=mock_build_artifact
    ):
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
        "documents": [
            {"path": str(claim_pdf), "doc_type": "cms1500", "has_text_layer": True}
        ],
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

    with patch(
        "claimflow.nodes.extract.extract", return_value=fake_result
    ) as mock_extract:
        from claimflow.nodes.extract import extract_node

        result = extract_node(state)

    assert mock_extract.called
    assert result["extraction_data"]["patient_name"] == "DOE JOHN"
    assert result["extraction_overall_confidence"] == 0.88
    assert result["extraction_status"] == "pass"


def test_extract_node_uses_regional_ocr_for_cms1500_image(tmp_path):
    """Dense CMS-1500 images use the layout-preserving regional OCR context."""

    image = tmp_path / "claim.png"
    image.write_bytes(b"placeholder")
    state = {
        "package_dir": str(tmp_path),
        "domain": "cms1500",
        "documents": [
            {
                "path": str(image),
                "doc_type": "cms1500",
                "has_text_layer": False,
            }
        ],
    }
    fake_result = MagicMock(
        data={"patient_name": "Salemy, Cheryl A"},
        fields=[],
        overall_confidence=0.95,
        status="pass",
    )

    with (
        patch(
            "claimflow.nodes.extract._cms1500_region_text",
            return_value="regional OCR text",
        ),
        patch(
            "claimflow.nodes.extract._extract_cms1500_text", return_value=fake_result
        ) as mock_cms1500_extract,
    ):
        from claimflow.nodes.extract import extract_node

        result = extract_node(state)

    mock_cms1500_extract.assert_called_once()
    args, kwargs = mock_cms1500_extract.call_args
    assert args[0] == "regional OCR text"
    assert args[1].name == "cms1500"
    assert result["extraction_overall_confidence"] == 0.95


def test_cms1500_region_corrections_keep_box_24_columns_aligned():
    from unittest.mock import MagicMock

    from claimflow.nodes.extract import (
        _cms1500_box_33a,
        _cms1500_service_lines,
        _correct_cms1500_result,
        _normalize_cms1500_date,
    )

    text = """
===== CMS-1500 PATIENT AND INSURED REGION =====
<td>13. INSURED'S OR AUTHORIZED PERSON'S SIGNATURE<br>SIGNED 13 signature here</td>
===== CMS-1500 CLAIM DETAILS REGION =====
14. DATE OF CURRENT ILLNESS MM DD YY 02 10 17 QUAL 123456
17. NAME OF REFERRING PROVIDER OR OTHER SOURCE
xx Smith, Jane MD
17a 17a 21-02215464
17b NPI 25-1987531
ICD Ind. E
===== CMS-1500 DIAGNOSES AND SERVICE LINES REGION =====
| 1 | 02 | 10 | 17 | 02 | 10 | 17 | 21 | 1C | 99201 | 01 | 02 | 03 | 04 | 1 | 125.00 | 1 | H | NPI | 25-1987555 |
| 2 | 02 | 10 | 17 | 02 | 10 | 17 | A33 | 2C | 11400 | 21 | 22 | 23 | 24 | 2 | 100.00 | 2 | H | NPI | 25-1234567 |
===== CMS-1500 PROVIDER AND TOTALS REGION =====
<table><tr><td>31. SIGNATURE OF PHYSICIAN OR SUPPLIER</td><td>32 SERVICE FACILITY LOCATION INFORMATION</td><td>33 BILLING PROVIDER INFO &amp; PH # (800) 111-2222</td></tr>
<tr><td>31 signature</td><td>Facility name</td><td>Facility name Billing Provider Info</td><td></td></tr>
<tr><td>SIGNED</td><td>112 Facility Road</td><td>33 Billing Provider Street</td></tr>
<tr><td>02/28/2017</td><td>Newtown, SC 88765</td><td>Billingstown NC 66554</td></tr>
<tr><td>a 32-216649a</td><td>b 32-245165b</td><td>a 33-216649a</td><td>b 33-245165b</td></tr></table>
===== CMS-1500 DIAGNOSIS INDICATOR REGION =====
<table><tr><th>ICO Ind</th><th>E</th></tr></table>
===== CMS-1500 TAX ID TYPE REGION =====
<table><tr><td>NUMBER</td><td>SSN</td><td>BN</td></tr><tr><td></td><td></td><td>X</td></tr></table>
"""

    lines = _cms1500_service_lines(text)
    assert lines == [
        {
            "cpt_code": "99201",
            "date_of_service": "02102017",
            "service_to_date": "02102017",
            "place_of_service": "21",
            "emergency_indicator": "1C",
            "diagnosis_pointer": "1",
            "charges": 125.0,
            "units": 1,
            "modifier": "01",
            "modifier_2": "02",
            "modifier_3": "03",
            "modifier_4": "04",
            "epsdt_family_plan": "H",
            "rendering_provider_id_qualifier": "NPI",
            "rendering_provider_npi": "25-1987555",
        },
        {
            "cpt_code": "11400",
            "date_of_service": "02102017",
            "service_to_date": "02102017",
            "place_of_service": "A33",
            "emergency_indicator": "2C",
            "diagnosis_pointer": "2",
            "charges": 100.0,
            "units": 2,
            "modifier": "21",
            "modifier_2": "22",
            "modifier_3": "23",
            "modifier_4": "24",
            "epsdt_family_plan": "H",
            "rendering_provider_id_qualifier": "NPI",
            "rendering_provider_npi": "25-1234567",
        },
    ]
    assert _cms1500_box_33a(text) == "33-216649a"
    assert _normalize_cms1500_date("101666") == "10161966"

    result = MagicMock()
    result.data = {
        "insurance_id": "Policy123456678",
        "insured_id": "Policy123456678",
        "referring_provider_name": "xx Smith, Jane MD",
        "service_facility_address": "112 Facility Road",
        "billing_provider_address": "33 Billing Provider Street",
    }
    result.fields = []
    _correct_cms1500_result(result, text)
    assert result.data["referring_provider_name"] == "Smith, Jane MD"
    assert result.data["insurance_id"] is None
    assert result.data["insured_signature_on_file"] is True
    assert result.data["date_of_current_illness_qualifier"] == "123456"
    assert result.data["referring_provider_qualifier"] == "xx"
    assert result.data.get("referring_provider_other_id_qualifier") is None
    assert result.data["referring_provider_other_id"] == "21-02215464"
    assert result.data["referring_provider_npi"] == "25-1987531"
    assert result.data["diagnosis_code_indicator"] == "E"
    assert result.data["federal_tax_id_type"] == "EIN"
    assert result.data["physician_signature_name"] == "31 signature"
    assert result.data["physician_signature_date"] == "02282017"
    assert result.data["service_date"] == "02282017"
    assert (
        result.data["service_facility_address"]
        == "112 Facility Road\nNewtown, SC 88765"
    )
    assert result.data["billing_provider_address"] == (
        "33 Billing Provider Street\nBillingstown NC 66554"
    )


def test_correct_cms1500_result_nulls_insurance_id_hallucinated_from_name():
    """Box 1a (INSURED'S I.D. NUMBER) is a numeric ID; if the LLM copies the
    patient/insured name into it (seen when box 1a is blank on the source form),
    that's a hallucination, not a real value."""
    from claimflow.nodes.extract import _correct_cms1500_result

    text = """
===== CMS-1500 PATIENT AND INSURED REGION =====
<td>1a. INSURED'S I.D. NUMBER<br>(For Program in Item 1)</td>
<td>2. PATIENT'S NAME<br>Salemy, Cheryl A</td>
===== CMS-1500 CLAIM DETAILS REGION =====
===== CMS-1500 DIAGNOSES AND SERVICE LINES REGION =====
===== CMS-1500 PROVIDER AND TOTALS REGION =====
"""
    result = MagicMock()
    result.data = {
        "insurance_id": "Salemy, Cheryl A",
        "insured_id": "Policy123456678",
        "patient_name": "Salemy, Cheryl A",
        "insured_name": "Salemy, Cheryl A",
    }
    result.fields = []
    _correct_cms1500_result(result, text)
    assert result.data["insurance_id"] is None


def test_correct_cms1500_result_nulls_insurance_id_when_box_1a_cell_is_blank():
    """Box 1a can be hallucinated with content copied from *any* nearby box, not
    just a name (see test above) -- the deterministic fix has to check the actual
    box 1a cell in the OCR'd table, not pattern-match specific leaked values."""
    from claimflow.nodes.extract import _correct_cms1500_result

    text = """
===== CMS-1500 PATIENT AND INSURED REGION =====
<table>
  <tr>
    <td colspan="2" rowspan="2">1. MEDICARE</td>
    <td colspan="2" rowspan="2">1a. INSURED'S I.D. NUMBER<br>(For Program in Item 1)</td>
  </tr>
  <tr>
    <td colspan="2">11. INSURED'S POLICY GROUP OR FECA NUMBER<br>Policy123456678</td>
  </tr>
</table>
===== CMS-1500 CLAIM DETAILS REGION =====
===== CMS-1500 DIAGNOSES AND SERVICE LINES REGION =====
===== CMS-1500 PROVIDER AND TOTALS REGION =====
"""
    result = MagicMock()
    result.data = {
        "insurance_id": "Policy123456678",
        "insured_id": "Policy123456678",
        "patient_name": "Salemy, Cheryl A",
        "insured_name": "Salemy, Cheryl A",
    }
    result.fields = []
    _correct_cms1500_result(result, text)
    assert result.data["insurance_id"] is None


def test_placeholder_fields_are_nulled_in_public_extraction_data():
    from unittest.mock import MagicMock

    from claimflow.nodes.extract import _null_placeholder_fields

    placeholder = MagicMock()
    placeholder.name = "claim_number"
    placeholder.parent_field = None
    placeholder.field_status = "redacted_or_placeholder"
    placeholder.value = "XXXXXX"
    result = MagicMock(data={"claim_number": "XXXXXX"}, fields=[placeholder])

    _null_placeholder_fields(result)

    assert result.data["claim_number"] is None
    assert placeholder.value is None


def test_eob_payer_requires_an_explicit_payer_label():
    from unittest.mock import MagicMock

    from claimflow.nodes.extract import _correct_eob_payer

    payer = MagicMock()
    payer.name = "payer_name"
    payer.parent_field = None
    payer.confidence = 1.0
    result = MagicMock(
        data={"payer_name": "Medicare"}, fields=[payer], overall_confidence=1.0
    )

    _correct_eob_payer(result, "CMS Medicare — How to Read Your EOB")

    assert result.data["payer_name"] is None
    assert payer.field_status == "not_found"
    assert result.overall_confidence == 0.3


def test_sba_form_413_reads_named_acroform_totals(tmp_path):
    from unittest.mock import MagicMock, patch

    from claimflow.nodes.extract import _correct_sba_form_413_widgets

    source = tmp_path / "form.pdf"
    source.touch()
    total = MagicMock()
    total.name = "total_assets"
    total.parent_field = None
    total.confidence = 0.3
    widget = MagicMock(field_name="TotalAssets", field_value="0")
    page = MagicMock()
    page.widgets.return_value = [widget]
    document = MagicMock()
    document.__enter__.return_value = [page]
    result = MagicMock(
        data={"total_assets": None}, fields=[total], overall_confidence=0.3
    )

    with patch("fitz.open", return_value=document):
        _correct_sba_form_413_widgets(result, source)

    assert result.data["total_assets"] == 0.0
    assert total.confidence == 1.0
    assert total.evidence.extraction_method == "acroform_widget"


def test_xactimate_page_schema_allows_page_local_partial_results():
    from doc_intel.inputs import DocumentBlock, DocumentLayout

    from claimflow.domains.base import get as get_domain
    from claimflow.nodes.extract import _xactimate_line_layouts, _xactimate_llm_specs

    summary_spec, line_spec = _xactimate_llm_specs(get_domain("xactimate").spec)

    assert "line_items" not in summary_spec.model.model_fields
    assert all(
        not field.is_required() for field in summary_spec.model.model_fields.values()
    )
    assert line_spec.model().line_items == []

    layout = DocumentLayout(
        blocks=[
            DocumentBlock(
                text="Header 1.  First 1 EA 2.00 2.00 2.  Second 1 EA 3.00 3.00",
                page=1,
                block_type="paragraph",
            )
        ]
    )
    chunks = _xactimate_line_layouts(layout, items_per_chunk=1)
    assert len(chunks) == 2
    assert "1.  First" in chunks[0].full_text
    assert "2.  Second" not in chunks[0].full_text


def test_xactimate_native_rows_preserve_every_line_and_amount(tmp_path):
    from claimflow.nodes.extract import _xactimate_native_line_items

    source = tmp_path / "estimate.pdf"
    page = MagicMock()
    page.get_text.return_value = (
        "  13. Seal the surface area w/latex based      20.00 SF"
        "       0.50       10.00       <1.33>       8.67\n"
        "  14. Paint the surface area - one coat       558.44 SF"
        "       0.53       295.97      <39.46>      256.51\n"
    )
    document = MagicMock()
    document.__enter__.return_value = [page]

    with patch("fitz.open", return_value=document):
        items = _xactimate_native_line_items(str(source))

    assert [item["line_number"] for item in items] == [13, 14]
    assert items[0]["total"] == 10.0
    assert items[1]["quantity"] == 558.44


def test_xactimate_native_rows_remove_separate_tax_from_line_total(tmp_path):
    from claimflow.nodes.extract import _xactimate_native_line_items

    source = tmp_path / "taxed-estimate.pdf"
    page = MagicMock()
    page.get_text.return_value = (
        "DESCRIPTION  QUANTITY  UNIT PRICE  TAX  RCV  DEPREC.  ACV\n"
        "  2. Laminated shingle roofing      60.00 SQ"
        "       185.00       559.08       11,659.08       (0.00)       11,659.08\n"
    )
    document = MagicMock()
    document.__enter__.return_value = [page]

    with patch("fitz.open", return_value=document):
        [item] = _xactimate_native_line_items(str(source))

    assert item["total"] == 11100.0


def test_review_node_approves_clean_claim():
    from claimflow.nodes.review import review_node
    from claimflow.state import ClaimState

    state: ClaimState = {
        "package_dir": "/tmp",
        "documents": [],
        "extraction_data": {},
        "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.90,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    result = review_node(state)
    assert result["decision"] == "approved"
    assert result["review_reasons"] == []


def test_review_node_flags_validation_failures():
    from claimflow.nodes.review import review_node
    from claimflow.state import ClaimState, ValidationFailure

    state: ClaimState = {
        "package_dir": "/tmp",
        "documents": [],
        "extraction_data": {},
        "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.85,
        "validation_failures": [
            ValidationFailure(
                field="total_charge", rule="arithmetic", reason="mismatch"
            )
        ],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    result = review_node(state)
    assert result["decision"] == "flagged"
    assert len(result["review_reasons"]) > 0


def test_review_node_escalates_low_confidence():
    from claimflow.nodes.review import review_node
    from claimflow.state import ClaimState

    state: ClaimState = {
        "package_dir": "/tmp",
        "documents": [],
        "extraction_data": {},
        "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.40,  # below escalation_threshold
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    result = review_node(state)
    assert result["decision"] == "escalated"


def test_graph_runs_end_to_end(tmp_path):
    """Graph executes all nodes and produces a decision."""

    claim_pdf = tmp_path / "claim.pdf"
    claim_pdf.write_bytes(b"placeholder")

    def mock_build_artifact(path):
        page = MagicMock()
        page.text = "HEALTH INSURANCE CLAIM FORM CMS-1500\nBox 1a: INS123"
        page.native_text_available = True
        page.ocr_used = False
        artifact = MagicMock()
        artifact.pages = [page]
        return artifact

    fake_extraction = MagicMock()
    fake_extraction.data = {
        "insurance_id": "INS123",
        "patient_name": "DOE JOHN",
        "patient_dob": "01011980",
        "billing_provider_npi": "1487293650",
        "diagnosis_codes": ["J06.9"],
        "service_lines": [
            {
                "cpt_code": "99213",
                "date_of_service": "01012026",
                "charges": "150.00",
                "units": 1,
                "place_of_service": "11",
                "diagnosis_pointer": "A",
            }
        ],  # noqa: E501
        "total_charge": "150.00",
        "signature_on_file": True,
    }
    fake_extraction.fields = []
    fake_extraction.overall_confidence = 0.88
    fake_extraction.status = "pass"

    with (
        patch("claimflow.nodes.ingest.build_artifact", side_effect=mock_build_artifact),
        patch("claimflow.nodes.extract.extract", return_value=fake_extraction),
        patch("claimflow.lookups.icd10.is_valid_icd10", return_value=True),
        patch("claimflow.lookups.cpt.is_valid_cpt", return_value=True),
    ):
        from claimflow.graph import build_graph

        app = build_graph()
        result = app.invoke(
            {"package_dir": str(tmp_path)},
            config={"configurable": {"thread_id": "test"}},
        )

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
        "package_dir": "/tmp",
        "documents": [],
        "extraction_data": {},
        "extraction_fields": [],
        "extraction_status": "pass",
        "extraction_overall_confidence": 0.9,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }
    result = retrieve_node(state)
    assert result["policy_answers"] == []


def test_cms_policy_question_targets_billing_provider_npi():
    from claimflow.nodes.retrieve import _failure_to_question

    question = _failure_to_question(
        {
            "field": "billing_provider_npi",
            "rule": "mandatory",
            "reason": "not a real NPI",
        },
        "cms1500",
    )

    assert "CMS-1500 Item 33a" in question


def test_policy_search_filters_to_the_claim_domain():
    from claimflow.nodes.retrieve import _search

    hit = MagicMock(
        document="All diagnosis codes must be valid ICD-10-CM codes.",
        score=0.9,
        metadata={
            "source": "cms_medicare_claims_processing_manual_ch26.pdf",
            "domain": "health",
            "authority": "official_cms",
        },
    )
    qdrant = MagicMock()
    qdrant.query.return_value = [hit]

    with patch("claimflow.nodes.retrieve._get_qdrant", return_value=qdrant):
        [result] = _search("diagnosis policy", "cms1500")

    query_filter = qdrant.query.call_args.kwargs["query_filter"]
    assert query_filter.must[0].match.value == "health"
    assert query_filter.must[1].match.value == "official_cms"
    assert result["source"] == "cms_medicare_claims_processing_manual_ch26.pdf"


def test_policy_answer_citations_include_source_and_excerpt():
    from claimflow.nodes.retrieve import _synthesize

    reranker = MagicMock()
    reranker.predict.return_value = [0.9]
    chunks = [
        {
            "text": "The NPI is a unique 10-digit numeric identifier.",
            "score": 0.8,
            "source": "cms_npi_fact_sheet.pdf",
        }
    ]

    with (
        patch("claimflow.nodes.retrieve._get_reranker", return_value=reranker),
        patch(
            "claimflow.nodes.retrieve._call_llm",
            return_value="It must be 10 digits [1].",
        ),
    ):
        answer = _synthesize("What is an NPI?", chunks)

    assert answer["citations"] == [
        "[1] cms_npi_fact_sheet.pdf — The NPI is a unique 10-digit numeric identifier."
    ]


def test_cms_policy_answer_is_deterministic_and_does_not_call_llm():
    from claimflow.nodes.retrieve import _synthesize

    chunks = [
        {
            "text": "The NPI is a unique 10-digit numeric identifier.",
            "score": 0.9,
            "source": "cms_npi_fact_sheet.pdf",
        }
    ]
    failure = {
        "field": "billing_provider_npi",
        "rule": "mandatory",
        "reason": "'ABC' does not look like a real NPI",
    }

    with patch("claimflow.nodes.retrieve._call_llm") as call_llm:
        answer = _synthesize(
            "What is required?",
            chunks,
            domain_key="cms1500",
            failure=failure,
        )

    call_llm.assert_not_called()
    assert "10-digit numeric identifier" in answer["answer"]
    assert "'ABC'" in answer["answer"]


def test_search_uses_domain_pack_policy_collection_not_hardcoded_dict(monkeypatch):
    from claimflow.domains import base as domains_base
    from claimflow.nodes.retrieve import _search

    fake_pack = domains_base.Domain(
        doc_type="_fake_domain", keywords=set(), spec=None, validate=lambda d: [],
        policy_collection="fake_collection",
    )
    domains_base.register(fake_pack)

    captured = {}

    class FakeQdrant:
        def query(self, **kwargs):
            captured["filter"] = kwargs["query_filter"]
            return []

    monkeypatch.setattr("claimflow.nodes.retrieve._get_qdrant", lambda: FakeQdrant())
    _search("question", "_fake_domain")
    assert "fake_collection" in str(captured["filter"])


def test_ingest_node_respects_doc_type_override(tmp_path):
    """A filename present in doc_type_overrides skips keyword classification entirely."""

    pkg = tmp_path / "package"
    pkg.mkdir()
    claim_pdf = pkg / "claim.pdf"
    claim_pdf.write_bytes(b"placeholder")

    fake_page = MagicMock()
    fake_page.text = "completely unrecognizable text with no keywords"
    fake_page.native_text_available = True
    fake_page.ocr_used = False
    fake_artifact = MagicMock()
    fake_artifact.pages = [fake_page]

    with patch("claimflow.nodes.ingest.build_artifact", return_value=fake_artifact):
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
            "doc_type_overrides": {"claim.pdf": "cms1500"},
        }
        result = ingest_node(state)

    docs = result["documents"]
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "cms1500"
    assert docs[0]["classification_reason"] == "manual override"
    assert result["domain"] == "cms1500"
