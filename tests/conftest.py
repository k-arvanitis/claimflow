import pytest


@pytest.fixture
def base_state():
    return {
        "package_dir": "/tmp",
        "domain": "cms1500",
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


@pytest.fixture
def clean_claim():
    return {
        "insurance_id": "INS123",
        "patient_name": "DOE JOHN",
        "patient_dob": "01011980",
        "patient_sex": "M",
        "insured_name": "DOE JOHN",
        "billing_provider_npi": "1487293650",
        "billing_provider_name": "SMITH MD JANE",
        "billing_provider_address": "123 MAIN ST CITY ST 12345",
        "federal_tax_id": "123456789",
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
        ],
        "total_charge": "150.00",
        "amount_paid": "0.00",
        "accept_assignment": True,
        "signature_on_file": True,
    }
