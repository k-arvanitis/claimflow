from decimal import Decimal

from claimflow.schemas.cms1500 import CMS1500, CMS1500_SPEC, ServiceLine


def test_settings_import():
    from claimflow.config import settings

    assert settings.llm_model == "claude-sonnet-4-6"


def test_cms1500_schema_instantiation():
    line = ServiceLine(
        cpt_code="99213",
        date_of_service="07012026",
        place_of_service="11",
        diagnosis_pointer="A",
        charges=Decimal("150.00"),
        units=1,
    )
    claim = CMS1500(
        insurance_id="ABC123456789",
        patient_name="DOE JOHN",
        patient_dob="01011980",
        patient_sex="M",
        insured_name="DOE JOHN",
        diagnosis_codes=["J06.9"],
        service_lines=[line],
        billing_provider_name="SMITH MD JANE",
        billing_provider_npi="1234567890",
        billing_provider_address="123 MAIN ST CITY ST 12345",
        total_charge=Decimal("150.00"),
        amount_paid=Decimal("0.00"),
        federal_tax_id="123456789",
        accept_assignment=True,
        signature_on_file=True,
    )
    assert claim.patient_name == "DOE JOHN"
    assert len(claim.service_lines) == 1
    assert claim.service_lines[0].cpt_code == "99213"


def test_spec_has_required_fields():
    assert CMS1500_SPEC.name == "cms1500"
    assert CMS1500_SPEC.model is CMS1500
    assert "CMS-1500" in CMS1500_SPEC.system_prompt


def test_cms1500_schema_covers_contact_and_full_service_line_fields():
    claim_fields = CMS1500.model_fields
    line_fields = ServiceLine.model_fields

    assert {
        "patient_phone",
        "insured_phone",
        "other_insured_name",
        "referring_provider_qualifier",
        "prior_authorization_number",
        "service_facility_npi",
        "billing_provider_phone",
        "billing_provider_other_id",
        "physician_signature_name",
        "physician_signature_date",
    } <= claim_fields.keys()
    assert {
        "service_to_date",
        "emergency_indicator",
        "epsdt_family_plan",
        "rendering_provider_id_qualifier",
    } <= line_fields.keys()
