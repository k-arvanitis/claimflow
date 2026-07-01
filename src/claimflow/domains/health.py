from datetime import date
from decimal import Decimal, InvalidOperation

import claimflow.lookups.cpt as _cpt
import claimflow.lookups.icd10 as _icd10
from claimflow.domains.base import Domain, register
from claimflow.state import ValidationFailure
from doc_intel.schemas.base import BaseExtraction, SchemaSpec
from pydantic import Field


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
    insurance_id: str = Field(description="Insured's ID number (Box 1a)")
    patient_name: str = Field(description="Patient last name, first name (Box 2)")
    patient_dob: str = Field(description="Patient date of birth MMDDYYYY (Box 3)")
    patient_sex: str = Field(description="Patient sex M or F (Box 3)")
    patient_address: str | None = Field(default=None, description="Patient address (Box 5)")
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
    system_prompt=(
        "Extract all fields from this CMS-1500 health insurance claim form. "
        "The form has numbered boxes — use the box numbers in field descriptions as anchors. "
        "For diagnosis codes extract only the code itself (e.g. J06.9), not descriptions. "
        "For dates use MMDDYYYY format as printed on the form. "
        "For boolean fields: 'X' or checked box = True, empty = False."
    ),
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


def _validate(data: dict) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for field in _MANDATORY:
        val = data.get(field)
        if not val and val != 0:
            failures.append(ValidationFailure(field=field, rule="mandatory",
                reason=f"{field} is required but missing or empty"))

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


HEALTH = Domain(
    doc_type="cms1500",
    keywords={"cms-1500", "health insurance claim form", "cms 1500"},
    spec=_SPEC,
    validate=_validate,
)

register(HEALTH)
