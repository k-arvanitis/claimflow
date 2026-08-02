import re
from datetime import date
from decimal import Decimal, InvalidOperation

from doc_intel.schemas.base import BaseExtraction, SchemaSpec
from pydantic import Field

from claimflow.domains.base import Domain, register
from claimflow.prompts import LOAN_EXTRACTION as _LOAN_PROMPT
from claimflow.prompts import SBA_FORM_413_EXTRACTION as _FORM_413_PROMPT
from claimflow.state import ValidationFailure

_BUSINESS_ENTITY_RE = r"\b(LLC|Inc|Corp|DBA|Partnership|Ltd|Enterprises|Solutions|Group|Industries|Services)\b"


def _parse_date(mmddyyyy: str) -> date | None:
    try:
        return date(int(mmddyyyy[4:8]), int(mmddyyyy[0:2]), int(mmddyyyy[2:4]))
    except Exception:
        return None


class LoanApplication(BaseExtraction):
    applicant_name: str | None = Field(
        default=None,
        description="Full legal name from the first row of the OWNERSHIP OF APPLICANT COMPANY "
        "table; null if that row is blank — do not substitute a different owner's name",
    )
    business_name: str | None = Field(
        default=None, description="Business name if commercial loan"
    )
    tax_id: str | None = Field(
        default=None,
        description="EIN or SSN tax ID exactly as printed, digits and dashes only; "
        "null if the field is blank — never output a format example as if it were a real value",
    )
    loan_amount_requested: float = Field(
        description="Total loan amount requested in dollars"
    )
    loan_purpose: str = Field(description="Purpose of the loan")
    gross_revenue: float | None = Field(
        default=None, description="Annual gross revenue"
    )
    net_income: float | None = Field(default=None, description="Annual net income")
    total_assets: float | None = Field(default=None, description="Total assets")
    total_liabilities: float | None = Field(
        default=None, description="Total liabilities"
    )
    signature_on_file: bool = Field(
        description="True only if the signature line is actually signed or marked; False if "
        "blank — the line/label itself is always printed whether or not it's signed",
    )


_SPEC = SchemaSpec(
    name="loan",
    model=LoanApplication,
    system_prompt=_LOAN_PROMPT,
)

_MANDATORY = [
    "applicant_name",
    "tax_id",
    "loan_amount_requested",
    "loan_purpose",
    "signature_on_file",
]


def _validate(data: dict) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for field in _MANDATORY:
        val = data.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            failures.append(
                ValidationFailure(
                    field=field,
                    rule="mandatory",
                    reason=f"{field} is required but missing or empty",
                    severity="error",
                    policy_required=False,
                )
            )

    # A real EIN/SSN is digits and dashes only. Models asked to extract a blank tax ID field
    # sometimes echo the format hint (e.g. "XX-XXXXXXX") back as if it were the real value —
    # catch that deterministically rather than trusting the model to self-report null.
    tax_id = data.get("tax_id")
    if tax_id and re.search(r"[A-Za-z]", str(tax_id)):
        failures.append(
            ValidationFailure(
                field="tax_id",
                rule="mandatory",
                reason=f"'{tax_id}' looks like a placeholder pattern, not a real tax ID",
                severity="error",
                policy_required=False,
            )
        )

    # A legal person's name doesn't contain business-entity markers. Models asked to extract
    # a blank applicant_name field sometimes substitute the business name from elsewhere on the
    # form instead of returning null — catch that deterministically.
    applicant_name = data.get("applicant_name")
    if applicant_name and re.search(
        _BUSINESS_ENTITY_RE, str(applicant_name), re.IGNORECASE
    ):
        failures.append(
            ValidationFailure(
                field="applicant_name",
                rule="mandatory",
                reason=f"'{applicant_name}' looks like a business name, not a person's name",
                severity="error",
                policy_required=False,
            )
        )

    # Loan amount must be positive
    try:
        amt = float(data.get("loan_amount_requested") or 0)
        if amt <= 0:
            failures.append(
                ValidationFailure(
                    field="loan_amount_requested",
                    rule="positive_amount",
                    reason="Loan amount must be greater than zero",
                    severity="error",
                    policy_required=True,
                )
            )
    except (TypeError, ValueError):
        pass

    # Net income must not exceed gross revenue
    try:
        gross = data.get("gross_revenue")
        net = data.get("net_income")
        if gross is not None and net is not None:
            if float(net) > float(gross):
                failures.append(
                    ValidationFailure(
                        field="net_income",
                        rule="income_consistency",
                        reason=f"Net income ${net} exceeds gross revenue ${gross}",
                        severity="warning",
                        policy_required=True,
                        machine_value=f"${net}",
                        expected_value=f"<= ${gross}",
                    )
                )
    except (TypeError, ValueError):
        pass

    # Signature required
    if data.get("signature_on_file") is False:
        failures.append(
            ValidationFailure(
                field="signature_on_file",
                rule="signature_required",
                reason="Application requires a valid signature",
                severity="error",
                policy_required=True,
            )
        )

    return failures


_SUPPORTING_TYPES = {
    "tax_return": {"form 1040", "form 1120", "internal revenue service", "tax return"},
    "bank_statement": {
        "account summary",
        "beginning balance",
        "ending balance",
        "statement period",
    },
    "balance_sheet": {
        "balance sheet",
        "total assets",
        "total liabilities",
        "shareholders equity",
    },
    "income_statement": {
        "income statement",
        "profit and loss",
        "net income",
        "total revenue",
    },
    "id_document": {
        "driver license",
        "passport",
        "date of birth",
        "social security number",
    },
    "supporting_exhibit": {
        "exhibit a",
        "exhibit b",
        "attachment",
        "supporting documentation",
    },
    # Classification-only — recognized and routed for manual triage, no extraction pipeline.
    "profit_loss_statement": {
        "profit & loss",
        "p&l statement",
        "statement of profit and loss",
    },
    "debt_schedule": {"debt schedule", "schedule of debts", "outstanding debt summary"},
    "business_license": {
        "business license",
        "license number",
        "certificate of occupancy",
    },
    "articles_of_incorporation": {
        "articles of incorporation",
        "certificate of incorporation",
        "articles of organization",
    },
    "payroll_report": {"payroll report", "payroll register", "pay period"},
    "w2_1099_paystub": {"form w-2", "form 1099", "pay stub", "earnings statement"},
}

LOAN = Domain(
    doc_type="loan",
    keywords={
        "sba loan application",
        "small business administration",
        "business loan application",
        "loan application",
        "loan request form",
    },
    spec=_SPEC,
    validate=_validate,
    supporting_types=_SUPPORTING_TYPES,
    display_name="SBA Loan Application",
    policy_collection="loan",
    question_templates={
        "income_consistency": "What is the policy when net income exceeds gross revenue on a loan application? {reason}",
        "positive_amount": "What is the minimum loan amount required? {reason}",
        "signature_required": "What happens when a loan application is missing a signature? {reason}",
    },
    client_name_field="applicant_name",
)

register(LOAN)


class SBAForm413(BaseExtraction):
    applicant_name: str | None = Field(
        default=None, description="Person completing the statement"
    )
    business_name: str | None = Field(
        default=None, description="Associated business name, if any"
    )
    as_of_date: str | None = Field(
        default=None, description="Statement 'as of' date MMDDYYYY"
    )
    cash_on_hand: float | None = Field(
        default=None, description="Cash on hand and in banks"
    )
    savings_accounts: float | None = Field(
        default=None, description="Savings account balances"
    )
    ira_retirement_accounts: float | None = Field(
        default=None, description="IRA/retirement account balances"
    )
    accounts_notes_receivable: float | None = Field(
        default=None, description="Accounts and notes receivable"
    )
    life_insurance_cash_surrender: float | None = Field(
        default=None, description="Life insurance cash surrender value"
    )
    stocks_bonds: float | None = Field(
        default=None, description="Stocks and bonds value"
    )
    real_estate: float | None = Field(default=None, description="Real estate value")
    automobiles: float | None = Field(default=None, description="Automobile value")
    other_personal_property: float | None = Field(
        default=None, description="Other personal property value"
    )
    total_assets: float | None = Field(
        default=None, description="Total assets — the form's own printed total"
    )
    accounts_payable: float | None = Field(default=None, description="Accounts payable")
    notes_payable: float | None = Field(default=None, description="Notes payable")
    installment_accounts_auto: float | None = Field(
        default=None, description="Installment account — automobile"
    )
    installment_accounts_other: float | None = Field(
        default=None, description="Installment account — other"
    )
    loan_on_life_insurance: float | None = Field(
        default=None, description="Loan against life insurance"
    )
    mortgages: float | None = Field(
        default=None, description="Mortgages on real estate"
    )
    unpaid_taxes: float | None = Field(default=None, description="Unpaid taxes")
    other_liabilities: float | None = Field(
        default=None, description="Other liabilities"
    )
    total_liabilities: float | None = Field(
        default=None, description="Total liabilities — the form's own printed total"
    )
    net_worth: float | None = Field(
        default=None, description="Net worth — the form's own printed total"
    )
    annual_income: float | None = Field(default=None, description="Annual income")
    contingent_liabilities: float | None = Field(
        default=None, description="Contingent liabilities"
    )


_FORM_413_SPEC = SchemaSpec(
    name="sba_form_413",
    model=SBAForm413,
    system_prompt=_FORM_413_PROMPT,
)


def _validate_form_413(data: dict) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    applicant_name = data.get("applicant_name")
    if applicant_name and re.search(
        _BUSINESS_ENTITY_RE, str(applicant_name), re.IGNORECASE
    ):
        failures.append(
            ValidationFailure(
                field="applicant_name",
                rule="mandatory",
                reason=f"'{applicant_name}' looks like a business name, not a person's name",
                severity="error",
                policy_required=False,
            )
        )

    as_of = _parse_date(data.get("as_of_date") or "")
    if as_of and as_of > date.today():
        failures.append(
            ValidationFailure(
                field="as_of_date",
                rule="date_window",
                reason="As-of date is in the future",
                severity="error",
                policy_required=False,
            )
        )

    amount_fields = [
        "cash_on_hand",
        "savings_accounts",
        "ira_retirement_accounts",
        "accounts_notes_receivable",
        "life_insurance_cash_surrender",
        "stocks_bonds",
        "real_estate",
        "automobiles",
        "other_personal_property",
        "total_assets",
        "accounts_payable",
        "notes_payable",
        "installment_accounts_auto",
        "installment_accounts_other",
        "loan_on_life_insurance",
        "mortgages",
        "unpaid_taxes",
        "other_liabilities",
        "total_liabilities",
        "annual_income",
        "contingent_liabilities",
    ]
    for field in amount_fields:
        val = data.get(field)
        try:
            if val is not None and float(val) < 0:
                failures.append(
                    ValidationFailure(
                        field=field,
                        rule="negative_amount",
                        reason=f"{field} cannot be negative",
                        severity="error",
                        policy_required=False,
                    )
                )
        except (TypeError, ValueError):
            pass

    total_assets, total_liabilities, net_worth = (
        data.get("total_assets"),
        data.get("total_liabilities"),
        data.get("net_worth"),
    )
    if (
        total_assets is not None
        and total_liabilities is not None
        and net_worth is not None
    ):
        try:
            computed = Decimal(str(total_assets)) - Decimal(str(total_liabilities))
            if abs(computed - Decimal(str(net_worth))) > Decimal("1.00"):
                failures.append(
                    ValidationFailure(
                        field="net_worth",
                        rule="arithmetic",
                        reason=f"total_assets ${total_assets} minus total_liabilities ${total_liabilities} "
                        f"does not equal net_worth ${net_worth}",
                        severity="warning",
                        policy_required=False,
                        machine_value=f"${computed}",
                        expected_value=f"${net_worth}",
                    )
                )
        except InvalidOperation:
            pass

    return failures


SBA_FORM_413 = Domain(
    doc_type="sba_form_413",
    keywords={
        "personal financial statement",
        "sba form 413",
        "schedule of real estate",
    },
    spec=_FORM_413_SPEC,
    validate=_validate_form_413,
    display_name="SBA Form 413 Personal Financial Statement",
    policy_collection="loan",
    client_name_field="applicant_name",
)
register(SBA_FORM_413)


class Liability(BaseExtraction):
    creditor_name: str = Field(description="Creditor name")
    original_amount: float | None = Field(
        default=None, description="Original loan/liability amount"
    )
    original_date: str | None = Field(
        default=None, description="Date the liability originated MMDDYYYY"
    )
    current_balance: float = Field(description="Current outstanding balance")
    maturity_date: str | None = Field(
        default=None, description="Maturity date MMDDYYYY"
    )
    payment_amount: float | None = Field(
        default=None, description="Periodic payment amount"
    )
    secured_by: str | None = Field(
        default=None, description="Collateral securing the liability"
    )
    current_or_delinquent: str | None = Field(
        default=None, description="'Current' or 'Delinquent' status"
    )


class SBAForm2202(BaseExtraction):
    liabilities: list[Liability] = Field(
        description="Schedule of liabilities line items"
    )
    total_current_balance: float | None = Field(
        default=None, description="Total current balance — form's own printed total"
    )


_FORM_2202_SPEC = SchemaSpec(
    name="sba_form_2202",
    model=SBAForm2202,
    system_prompt=(
        "Extract the schedule of liabilities from this SBA Form 2202. Each row lists a creditor, "
        "original amount, original date, current balance, maturity date, payment amount, what "
        "secures the debt, and current/delinquent status. Extract dollar amounts as numbers "
        "without currency symbols and dates as MMDDYYYY. If a row is blank, omit it rather than "
        "inventing placeholder values."
    ),
)


def _validate_form_2202(data: dict) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    liabilities = data.get("liabilities") or []

    for liability in liabilities:
        balance = liability.get("current_balance")
        try:
            if balance is not None and float(balance) < 0:
                failures.append(
                    ValidationFailure(
                        field="liabilities",
                        rule="negative_amount",
                        reason=f"current_balance cannot be negative for '{liability.get('creditor_name')}'",
                        severity="error",
                        policy_required=False,
                    )
                )
        except (TypeError, ValueError):
            pass

        payment = liability.get("payment_amount")
        try:
            if payment is not None and float(payment) < 0:
                failures.append(
                    ValidationFailure(
                        field="liabilities",
                        rule="negative_amount",
                        reason=f"payment_amount cannot be negative for '{liability.get('creditor_name')}'",
                        severity="error",
                        policy_required=False,
                    )
                )
        except (TypeError, ValueError):
            pass

        original_date = _parse_date(liability.get("original_date") or "")
        maturity_date = _parse_date(liability.get("maturity_date") or "")
        if original_date and maturity_date and maturity_date < original_date:
            failures.append(
                ValidationFailure(
                    field="liabilities",
                    rule="date_window",
                    reason=f"maturity_date is before original_date for '{liability.get('creditor_name')}'",
                    severity="warning",
                    policy_required=False,
                )
            )

        original_amount, current_balance = liability.get("original_amount"), balance
        status = str(liability.get("current_or_delinquent") or "").lower()
        if (
            original_amount is not None
            and current_balance is not None
            and status not in ("revolving", "deferred", "unknown", "")
        ):
            try:
                if float(current_balance) > float(original_amount):
                    failures.append(
                        ValidationFailure(
                            field="liabilities",
                            rule="amount_consistency",
                            reason=f"current_balance ${current_balance} exceeds original_amount "
                            f"${original_amount} for '{liability.get('creditor_name')}'",
                            severity="warning",
                            policy_required=False,
                            machine_value=f"${current_balance}",
                            expected_value=f"<= ${original_amount}",
                        )
                    )
            except (TypeError, ValueError):
                pass

    total = data.get("total_current_balance")
    if total is not None:
        try:
            computed = sum(
                Decimal(str(liability.get("current_balance", "0")))
                for liability in liabilities
            )
            if abs(computed - Decimal(str(total))) > Decimal("1.00"):
                failures.append(
                    ValidationFailure(
                        field="total_current_balance",
                        rule="arithmetic",
                        reason=f"Liabilities sum ${computed} does not match total_current_balance ${total}",
                        severity="warning",
                        policy_required=False,
                        machine_value=f"${computed}",
                        expected_value=f"${total}",
                    )
                )
        except InvalidOperation:
            pass

    return failures


SBA_FORM_2202 = Domain(
    doc_type="sba_form_2202",
    keywords={"sba form 2202", "schedule of liabilities"},
    spec=_FORM_2202_SPEC,
    validate=_validate_form_2202,
    display_name="SBA Form 2202 Schedule of Liabilities",
    policy_collection="loan",
)
register(SBA_FORM_2202)
