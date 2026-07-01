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
    # Patient (Box 1a, 2, 3, 5)
    insurance_id: str = Field(description="Insured's ID number (Box 1a)")
    patient_name: str = Field(description="Patient last name, first name (Box 2)")
    patient_dob: str = Field(description="Patient date of birth MMDDYYYY (Box 3)")
    patient_sex: str = Field(description="Patient sex M or F (Box 3)")
    patient_address: str | None = Field(default=None, description="Patient address (Box 5)")

    # Insured (Box 4, 11)
    insured_name: str = Field(description="Insured's name (Box 4)")
    insured_id: str | None = Field(default=None, description="Insured's policy/group number (Box 11)")

    # Condition (Box 14)
    date_of_current_illness: str | None = Field(default=None, description="Date of current illness MMDDYYYY (Box 14)")

    # Referring provider (Box 17, 17b)
    referring_provider_name: str | None = Field(default=None, description="Referring provider name (Box 17)")
    referring_provider_npi: str | None = Field(default=None, description="Referring provider NPI (Box 17b)")

    # Hospitalization (Box 18)
    hospitalization_from: str | None = Field(default=None, description="Hospitalization from date MMDDYYYY (Box 18)")
    hospitalization_to: str | None = Field(default=None, description="Hospitalization to date MMDDYYYY (Box 18)")

    # Diagnosis (Box 21) — up to 12 ICD-10 codes
    diagnosis_codes: list[str] = Field(description="ICD-10-CM diagnosis codes A through L (Box 21)")

    # Service lines (Box 24) — up to 6
    service_lines: list[ServiceLine] = Field(description="Service line items (Box 24)")

    # Billing provider (Box 25, 27, 28, 29, 31, 33, 33a)
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


CMS1500_SPEC = SchemaSpec(
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
