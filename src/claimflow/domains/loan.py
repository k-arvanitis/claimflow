from claimflow.domains.base import Domain, register
from claimflow.state import ValidationFailure
from doc_intel.schemas.base import BaseExtraction, SchemaSpec
from pydantic import Field


class LoanApplication(BaseExtraction):
    applicant_name: str = Field(description="Full legal name of primary applicant")
    business_name: str | None = Field(default=None, description="Business name if commercial loan")
    tax_id: str = Field(description="EIN (XX-XXXXXXX) or SSN (XXX-XX-XXXX)")
    loan_amount_requested: float = Field(description="Total loan amount requested in dollars")
    loan_purpose: str = Field(description="Purpose of the loan")
    gross_revenue: float | None = Field(default=None, description="Annual gross revenue")
    net_income: float | None = Field(default=None, description="Annual net income")
    total_assets: float | None = Field(default=None, description="Total assets")
    total_liabilities: float | None = Field(default=None, description="Total liabilities")
    signature_on_file: bool = Field(description="Applicant signature present")


_SPEC = SchemaSpec(
    name="loan",
    model=LoanApplication,
    system_prompt=(
        "Extract all fields from this SBA loan application or business loan form. "
        "Tax ID may appear as EIN (XX-XXXXXXX) or SSN (XXX-XX-XXXX). "
        "Extract dollar amounts as numbers without currency symbols. "
        "Signature on file is True if a signature block is present and signed."
    ),
)

_MANDATORY = [
    "applicant_name", "tax_id", "loan_amount_requested", "loan_purpose", "signature_on_file",
]


def _validate(data: dict) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for field in _MANDATORY:
        val = data.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            failures.append(ValidationFailure(field=field, rule="mandatory",
                reason=f"{field} is required but missing or empty"))

    # Loan amount must be positive
    try:
        amt = float(data.get("loan_amount_requested") or 0)
        if amt <= 0:
            failures.append(ValidationFailure(field="loan_amount_requested", rule="positive_amount",
                reason="Loan amount must be greater than zero"))
    except (TypeError, ValueError):
        pass

    # Net income must not exceed gross revenue
    try:
        gross = data.get("gross_revenue")
        net = data.get("net_income")
        if gross is not None and net is not None:
            if float(net) > float(gross):
                failures.append(ValidationFailure(field="net_income", rule="income_consistency",
                    reason=f"Net income ${net} exceeds gross revenue ${gross}"))
    except (TypeError, ValueError):
        pass

    # Signature required
    if data.get("signature_on_file") is False:
        failures.append(ValidationFailure(field="signature_on_file", rule="signature_required",
            reason="Application requires a valid signature"))

    return failures


LOAN = Domain(
    doc_type="loan",
    keywords={"sba loan application", "small business administration", "business loan application", "loan application"},
    spec=_SPEC,
    validate=_validate,
)

register(LOAN)
