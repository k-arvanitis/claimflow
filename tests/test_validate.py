from unittest.mock import patch

import pytest


@pytest.fixture
def clean_claim():
    return {
        "insurance_id": "INS123",
        "patient_name": "DOE JOHN",
        "patient_dob": "01011980",
        "billing_provider_npi": "1234567890",
        "diagnosis_codes": ["J06.9"],
        "service_lines": [
            {"cpt_code": "99213", "date_of_service": "01012026", "charges": "150.00", "units": 1, "place_of_service": "11", "diagnosis_pointer": "A"},  # noqa: E501
        ],
        "total_charge": "150.00",
        "signature_on_file": True,
    }


def test_clean_claim_no_failures(clean_claim):
    with patch("claimflow.lookups.icd10.is_valid_icd10", return_value=True), \
         patch("claimflow.lookups.cpt.is_valid_cpt", return_value=True):
        from claimflow.nodes.validate import validate_node
        from claimflow.state import ClaimState
        state: ClaimState = {
            "package_dir": "/tmp",
            "documents": [],
            "extraction_data": clean_claim,
            "extraction_fields": [],
            "extraction_status": "pass",
            "extraction_overall_confidence": 0.9,
            "validation_failures": [],
            "policy_answers": [],
            "decision": None,
            "review_reasons": [],
            "error": None,
        }
        result = validate_node(state)
        assert result["validation_failures"] == []


def test_missing_npi_flagged(clean_claim):
    clean_claim["billing_provider_npi"] = ""
    with patch("claimflow.lookups.icd10.is_valid_icd10", return_value=True), \
         patch("claimflow.lookups.cpt.is_valid_cpt", return_value=True):
        from claimflow.nodes.validate import validate_node
        from claimflow.state import ClaimState
        state: ClaimState = {
            "package_dir": "/tmp", "documents": [],
            "extraction_data": clean_claim, "extraction_fields": [],
            "extraction_status": "pass", "extraction_overall_confidence": 0.9,
            "validation_failures": [], "policy_answers": [],
            "decision": None, "review_reasons": [], "error": None,
        }
        result = validate_node(state)
        fields = [f["field"] for f in result["validation_failures"]]
        assert "billing_provider_npi" in fields


def test_arithmetic_mismatch_flagged(clean_claim):
    clean_claim["total_charge"] = "200.00"  # line sum is 150.00
    with patch("claimflow.lookups.icd10.is_valid_icd10", return_value=True), \
         patch("claimflow.lookups.cpt.is_valid_cpt", return_value=True):
        from claimflow.nodes.validate import validate_node
        from claimflow.state import ClaimState
        state: ClaimState = {
            "package_dir": "/tmp", "documents": [],
            "extraction_data": clean_claim, "extraction_fields": [],
            "extraction_status": "pass", "extraction_overall_confidence": 0.9,
            "validation_failures": [], "policy_answers": [],
            "decision": None, "review_reasons": [], "error": None,
        }
        result = validate_node(state)
        rules = [f["rule"] for f in result["validation_failures"]]
        assert "arithmetic" in rules


def test_invalid_icd10_flagged(clean_claim):
    clean_claim["diagnosis_codes"] = ["XXXXX"]
    with patch("claimflow.lookups.icd10.is_valid_icd10", return_value=False), \
         patch("claimflow.lookups.cpt.is_valid_cpt", return_value=True):
        from claimflow.nodes.validate import validate_node
        from claimflow.state import ClaimState
        state: ClaimState = {
            "package_dir": "/tmp", "documents": [],
            "extraction_data": clean_claim, "extraction_fields": [],
            "extraction_status": "pass", "extraction_overall_confidence": 0.9,
            "validation_failures": [], "policy_answers": [],
            "decision": None, "review_reasons": [], "error": None,
        }
        result = validate_node(state)
        rules = [f["rule"] for f in result["validation_failures"]]
        assert "icd10_lookup" in rules
