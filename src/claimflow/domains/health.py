import re
from datetime import date
from decimal import Decimal, InvalidOperation

from doc_intel.schemas.base import BaseExtraction, SchemaSpec
from pydantic import Field

import claimflow.lookups.cpt as _cpt
import claimflow.lookups.icd10 as _icd10
from claimflow.domains.base import Domain, register
from claimflow.prompts import EOB_EXTRACTION as _EOB_PROMPT
from claimflow.prompts import HEALTH_EXTRACTION as _HEALTH_PROMPT
from claimflow.state import ValidationFailure


class ServiceLine(BaseExtraction):
    cpt_code: str = Field(description="CPT procedure code (5 digits)")
    date_of_service: str = Field(description="Date of service MMDDYYYY")
    place_of_service: str = Field(description="2-digit place of service code")
    diagnosis_pointer: str = Field(description="Diagnosis code pointer(s): A, B, C, D")
    charges: float = Field(description="Dollar amount charged for this line")
    units: int = Field(description="Number of units/days")
    modifier: str | None = Field(default=None, description="CPT modifier code")
    rendering_provider_npi: str | None = Field(default=None, description="Rendering provider NPI if different from billing")  # noqa: E501


class CMS1500(BaseExtraction):
    insurance_id: str | None = Field(
        default=None, description="Insured's ID number (Box 1a); null if the box is blank",
    )
    patient_name: str = Field(description="Patient last name, first name (Box 2)")
    patient_dob: str = Field(description="Patient date of birth MMDDYYYY (Box 3)")
    patient_sex: str = Field(description="Patient sex M or F (Box 3)")
    patient_address: str | None = Field(
        default=None,
        description="Patient street address only (Box 5) — the first line under "
        "'PATIENT'S ADDRESS (No., Street)', e.g. '135 PARK BLVD'. Extract this in addition to, "
        "not instead of, patient_city/state/zip below — they are four separate fields from one box.",
    )
    patient_city: str | None = Field(default=None, description="Patient city (Box 5)")
    patient_state: str | None = Field(default=None, description="Patient state (Box 5)")
    patient_zip: str | None = Field(default=None, description="Patient ZIP code (Box 5)")
    insured_name: str = Field(description="Insured's name (Box 4)")
    insured_id: str | None = Field(default=None, description="Insured's policy/group number (Box 11)")
    date_of_current_illness: str | None = Field(default=None, description="Date of current illness MMDDYYYY (Box 14)")
    referring_provider_name: str | None = Field(default=None, description="Referring provider name (Box 17)")
    referring_provider_npi: str | None = Field(default=None, description="Referring provider NPI (Box 17b)")
    hospitalization_from: str | None = Field(default=None, description="Hospitalization from date MMDDYYYY (Box 18)")
    hospitalization_to: str | None = Field(default=None, description="Hospitalization to date MMDDYYYY (Box 18)")
    diagnosis_codes: list[str] = Field(description="ICD-10-CM diagnosis codes A through L (Box 21)")
    service_lines: list[ServiceLine] = Field(description="Service line items (Box 24)")
    federal_tax_id: str = Field(description="Federal tax ID (Box 25)")
    patient_account_number: str | None = Field(default=None, description="Patient account number (Box 26)")
    accept_assignment: bool = Field(description="Accept assignment YES/NO (Box 27)")
    total_charge: float = Field(description="Total charge (Box 28)")
    amount_paid: float = Field(description="Amount paid (Box 29)")
    billing_provider_name: str = Field(description="Billing provider name (Box 33)")
    billing_provider_npi: str = Field(description="Billing provider NPI (Box 33a)")
    billing_provider_address: str = Field(description="Billing provider address (Box 33)")
    signature_on_file: bool = Field(description="Physician signature on file (Box 31)")
    service_date: str | None = Field(default=None, description="Service date on signature line MMDDYYYY (Box 31)")


_SPEC = SchemaSpec(
    name="cms1500",
    model=CMS1500,
    system_prompt=_HEALTH_PROMPT,
)

_MANDATORY = [
    "insurance_id", "patient_name", "patient_dob",
    "billing_provider_npi", "diagnosis_codes", "service_lines", "total_charge",
]


def _parse_date(mmddyyyy: str) -> date | None:
    try:
        return date(int(mmddyyyy[4:8]), int(mmddyyyy[0:2]), int(mmddyyyy[2:4]))
    except Exception:
        return None


def _looks_fabricated(digits: str) -> bool:
    """All-one-digit or a simple ascending/descending run (e.g. '1234567890') —
    a real 10-digit identifier essentially never lands on one of these by chance."""
    if len(set(digits)) == 1:
        return True
    ascending = "".join(str((int(digits[0]) + i) % 10) for i in range(len(digits)))
    descending = "".join(str((int(digits[0]) - i) % 10) for i in range(len(digits)))
    return digits in (ascending, descending)


def _validate(data: dict) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for field in _MANDATORY:
        val = data.get(field)
        if not val and val != 0:
            failures.append(ValidationFailure(field=field, rule="mandatory",
                reason=f"{field} is required but missing or empty"))

    # A real NPI is always exactly 10 digits. Models asked to extract a blank NPI field
    # sometimes fabricate a plausible-looking number instead of returning empty — catch
    # any wrong-length value, or an obviously fabricated digit pattern (all one digit, or
    # a simple ascending/descending run), deterministically rather than trusting the
    # model's self-report. (A real NPI check-digit algorithm exists but isn't implemented
    # here — verifying it correctly needs a confirmed reference example, not memory.)
    npi = data.get("billing_provider_npi")
    if npi and (not re.fullmatch(r"\d{10}", str(npi)) or _looks_fabricated(str(npi))):
        failures.append(ValidationFailure(field="billing_provider_npi", rule="mandatory",
            reason=f"'{npi}' does not look like a real NPI — treating as missing"))

    for code in data.get("diagnosis_codes") or []:
        if code and not _icd10.is_valid_icd10(code):
            failures.append(ValidationFailure(field="diagnosis_codes", rule="icd10_lookup",
                reason=f"'{code}' is not a recognized ICD-10-CM code"))

    lines = data.get("service_lines") or []

    for line in lines:
        cpt = line.get("cpt_code", "")
        if cpt and not _cpt.is_valid_cpt(cpt):
            failures.append(ValidationFailure(field="service_lines", rule="cpt_lookup",
                reason=f"CPT '{cpt}' is not a recognized procedure code"))

    try:
        computed = sum(Decimal(str(line.get("charges", "0"))) for line in lines)
        total = Decimal(str(data.get("total_charge", "0")))
        if abs(computed - total) > Decimal("0.01"):
            failures.append(ValidationFailure(field="total_charge", rule="arithmetic",
                reason=f"Line sum ${computed} does not match total charge ${total}"))
    except InvalidOperation:
        failures.append(ValidationFailure(field="total_charge", rule="arithmetic",
            reason="Could not parse charge amounts as decimal numbers"))

    today = date.today()
    for line in lines:
        dos = _parse_date(line.get("date_of_service", ""))
        if dos and dos > today:
            failures.append(ValidationFailure(field="service_lines", rule="date_window",
                reason=f"Date of service {line['date_of_service']} is in the future"))

    return failures


_SUPPORTING_TYPES = {
    "medical_bill": {"statement of charges", "patient balance", "amount due", "billing statement"},
    "insurance_policy": {"policy number", "summary of benefits", "coverage period", "certificate of insurance"},
    "denial_letter": {"claim denied", "denial of coverage", "notice of denial", "adverse determination"},
    "clinical_note": {"chief complaint", "assessment and plan", "progress note", "history of present illness"},
    "lab_report": {"lab report", "laboratory results", "reference range", "specimen collected"},
    "discharge_summary": {"discharge summary", "discharge diagnosis", "discharge instructions"},
    "referral_letter": {"referral letter", "referring you to", "please see this patient"},
    # Classification-only — recognized and routed for manual triage, no extraction pipeline.
    "prior_authorization_letter": {"prior authorization", "preauthorization", "precertification"},
    "eligibility_benefits_verification": {"eligibility verification", "benefits verification", "coverage verification"},
    # UB-04/CMS-1450: classified only. Full production support needs licensed NUBC/AHA
    # data specs, not shipped here — see README known limitations.
    "ub04_cms1450": {"ub-04", "cms-1450", "uniform billing"},
}

HEALTH = Domain(
    doc_type="cms1500",
    keywords={"cms-1500", "health insurance claim form", "cms 1500"},
    spec=_SPEC,
    validate=_validate,
    supporting_types=_SUPPORTING_TYPES,
)

register(HEALTH)


class EOB(BaseExtraction):
    payer_name: str | None = Field(default=None, description="Insurer/Medicare name issuing this notice")
    patient_name: str = Field(description="Patient name")
    provider_name: str | None = Field(default=None, description="Rendering provider/facility name")
    claim_number: str | None = Field(default=None, description="Claim number; null if the field is blank")
    service_date: str | None = Field(default=None, description="Date of service MMDDYYYY")
    service_description: str | None = Field(default=None, description="Service/procedure description")
    provider_charges: float | None = Field(default=None, description="Amount the provider billed")
    allowed_charges: float | None = Field(default=None, description="Payer's approved amount")
    plan_paid: float | None = Field(default=None, description="Amount paid by the insurer/Medicare")
    patient_responsibility: float | None = Field(default=None, description="Amount owed by the patient")
    deductible_amount: float | None = Field(default=None, description="Deductible portion applied")
    coinsurance_amount: float | None = Field(default=None, description="Coinsurance portion applied")
    copay_amount: float | None = Field(default=None, description="Copay portion applied")
    denial_or_remark_codes: list[str] = Field(default_factory=list, description="Remark/denial codes (e.g. CO-45)")
    is_bill: bool = Field(description="True only if the document presents itself as a bill requiring payment")


_EOB_SPEC = SchemaSpec(
    name="eob",
    model=EOB,
    system_prompt=_EOB_PROMPT,
)

_EOB_MANDATORY = ["patient_name", "is_bill"]


def _validate_eob(data: dict) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for field in _EOB_MANDATORY:
        val = data.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            failures.append(ValidationFailure(field=field, rule="mandatory",
                reason=f"{field} is required but missing or empty"))

    # An EOB/MSN is informational by design ("This is not a bill" is standard boilerplate);
    # is_bill=True on this document type is itself the anomaly worth flagging.
    if data.get("is_bill") is True:
        failures.append(ValidationFailure(field="is_bill", rule="not_a_bill",
            reason="EOB/MSN documents are informational, not bills — is_bill=True is unexpected"))

    for field in ("provider_charges", "allowed_charges", "plan_paid", "patient_responsibility"):
        val = data.get(field)
        try:
            if val is not None and float(val) < 0:
                failures.append(ValidationFailure(field=field, rule="negative_amount",
                    reason=f"{field} cannot be negative"))
        except (TypeError, ValueError):
            pass

    provider_charges, allowed_charges = data.get("provider_charges"), data.get("allowed_charges")
    if provider_charges is not None and allowed_charges is not None:
        try:
            if float(provider_charges) < float(allowed_charges):
                failures.append(ValidationFailure(field="provider_charges", rule="amount_consistency",
                    reason=f"provider_charges ${provider_charges} is less than allowed_charges ${allowed_charges}"))
        except (TypeError, ValueError):
            pass

    claim_number = data.get("claim_number")
    if claim_number and not re.search(r"\d", str(claim_number)):
        failures.append(ValidationFailure(field="claim_number", rule="mandatory",
            reason=f"'{claim_number}' has no digits — looks like a placeholder, not a claim number"))

    service_date = _parse_date(data.get("service_date") or "")
    if service_date and service_date > date.today():
        failures.append(ValidationFailure(field="service_date", rule="date_window",
            reason="Service date is in the future"))

    return failures


EOB_DOMAIN = Domain(
    doc_type="eob",
    keywords={"explanation of benefits", "eob", "this is not a bill", "amount you may be billed"},
    spec=_EOB_SPEC,
    validate=_validate_eob,
)
register(EOB_DOMAIN)

# Medicare Summary Notice shares the EOB schema/validator (same underlying document
# concept, Medicare-specific terminology) — registered separately so it classifies
# under its own label instead of being folded into "eob".
MEDICARE_SUMMARY_NOTICE = Domain(
    doc_type="medicare_summary_notice",
    keywords={"medicare summary notice", "msn"},
    spec=SchemaSpec(name="medicare_summary_notice", model=EOB, system_prompt=_EOB_PROMPT),
    validate=_validate_eob,
)
register(MEDICARE_SUMMARY_NOTICE)
