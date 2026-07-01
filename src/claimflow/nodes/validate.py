from datetime import date
from decimal import Decimal, InvalidOperation

import claimflow.lookups.cpt as _cpt
import claimflow.lookups.icd10 as _icd10
from claimflow.state import ClaimState, ValidationFailure

_MANDATORY = [
    "insurance_id", "patient_name", "patient_dob",
    "billing_provider_npi", "diagnosis_codes", "service_lines", "total_charge",
]


def _parse_date(mmddyyyy: str) -> date | None:
    try:
        return date(int(mmddyyyy[4:8]), int(mmddyyyy[0:2]), int(mmddyyyy[2:4]))
    except Exception:
        return None


def validate_node(state: ClaimState) -> dict:
    data = state.get("extraction_data") or {}
    failures: list[ValidationFailure] = []

    # 1. Mandatory fields
    for field in _MANDATORY:
        val = data.get(field)
        if not val and val != 0:
            failures.append(ValidationFailure(
                field=field, rule="mandatory",
                reason=f"{field} is required but missing or empty",
            ))

    # 2. ICD-10 validity
    for code in data.get("diagnosis_codes") or []:
        if code and not _icd10.is_valid_icd10(code):
            failures.append(ValidationFailure(
                field="diagnosis_codes", rule="icd10_lookup",
                reason=f"'{code}' is not a recognized ICD-10-CM code",
            ))

    lines = data.get("service_lines") or []

    # 3. CPT validity
    for line in lines:
        cpt = line.get("cpt_code", "")
        if cpt and not _cpt.is_valid_cpt(cpt):
            failures.append(ValidationFailure(
                field="service_lines", rule="cpt_lookup",
                reason=f"CPT '{cpt}' is not a recognized procedure code",
            ))

    # 4. Arithmetic rollup
    try:
        computed = sum(Decimal(str(line.get("charges", "0"))) for line in lines)
        total = Decimal(str(data.get("total_charge", "0")))
        if abs(computed - total) > Decimal("0.01"):
            failures.append(ValidationFailure(
                field="total_charge", rule="arithmetic",
                reason=f"Line sum ${computed} does not match total charge ${total}",
            ))
    except InvalidOperation:
        failures.append(ValidationFailure(
            field="total_charge", rule="arithmetic",
            reason="Could not parse charge amounts as decimal numbers",
        ))

    # 5. Date of service not in future
    today = date.today()
    for line in lines:
        dos_str = line.get("date_of_service", "")
        dos = _parse_date(dos_str) if dos_str else None
        if dos and dos > today:
            failures.append(ValidationFailure(
                field="service_lines", rule="date_window",
                reason=f"Date of service {dos_str} is in the future",
            ))

    return {"validation_failures": failures}
