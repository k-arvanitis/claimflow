import re
from datetime import date
from decimal import Decimal, InvalidOperation

from doc_intel.schemas.base import BaseExtraction, SchemaSpec
from pydantic import Field
from rapidfuzz import fuzz

from claimflow.domains.base import Domain, register
from claimflow.prompts import DECLARATIONS_PAGE_EXTRACTION as _DECLARATIONS_PROMPT
from claimflow.prompts import PROPERTY_EXTRACTION as _PROPERTY_PROMPT
from claimflow.state import ValidationFailure


class LineItem(BaseExtraction):
    line_number: int | None = Field(
        default=None, description="Source estimate line number"
    )
    category: str = Field(description="Work category (e.g. Roofing, Drywall)")
    description: str = Field(description="Line item description")
    quantity: float = Field(description="Quantity")
    unit: str = Field(description="Unit of measure (SF, LF, EA, HR)")
    unit_cost: float = Field(description="Unit cost in dollars")
    total: float = Field(description="Line total = quantity × unit_cost")


class XactimatePDF(BaseExtraction):
    claim_number: str | None = Field(
        default=None,
        description="Insurance claim number; null if the field is blank on the form",
    )
    insured_name: str | None = Field(
        default=None,
        description="Name of insured property owner; null when absent or redacted",
    )
    property_address: str | None = Field(
        default=None,
        description="Full address of damaged property; null when absent or redacted",
    )
    date_of_loss: str | None = Field(
        default=None,
        description="Date of loss MMDDYYYY; do not substitute estimate/entry dates",
    )
    cause_of_loss: str | None = Field(
        default=None, description="Cause of loss (e.g. Wind, Water, Fire)"
    )
    adjuster_name: str | None = Field(
        default=None, description="Name of claims adjuster"
    )
    line_items: list[LineItem] = Field(
        default_factory=list,
        description="Itemized repair/replacement lines; empty on summary-only estimates",
    )
    line_item_total: float | None = Field(
        default=None,
        description="Printed line-item subtotal before overhead, profit, and tax",
    )
    overhead: float | None = Field(default=None, description="Printed overhead amount")
    profit: float | None = Field(
        default=None, description="Printed contractor profit amount"
    )
    material_sales_tax: float | None = Field(
        default=None, description="Printed material sales tax amount"
    )
    total_replacement_cost: float = Field(
        description="Total replacement cost value (RCV)"
    )
    depreciation: float = Field(description="Total depreciation amount")
    actual_cash_value: float = Field(
        description="Actual cash value = RCV minus depreciation"
    )
    deductible: float | None = Field(
        default=None, description="Policy deductible amount"
    )


_SPEC = SchemaSpec(
    name="xactimate",
    model=XactimatePDF,
    system_prompt=_PROPERTY_PROMPT,
)

_MANDATORY = [
    "total_replacement_cost",
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
            failures.append(
                ValidationFailure(
                    field=field,
                    rule="mandatory",
                    reason=f"{field} is required but missing or empty",
                    severity="error",
                    policy_required=False,
                )
            )

    # A real claim/reference number always contains at least one digit, regardless of the
    # insurer's specific prefix convention. Models asked to extract a blank claim number
    # sometimes substitute a name from elsewhere on the form instead of returning null.
    claim_number = data.get("claim_number")
    if claim_number and not re.search(r"\d", str(claim_number)):
        failures.append(
            ValidationFailure(
                field="claim_number",
                rule="mandatory",
                reason=f"'{claim_number}' has no digits — looks like a name, not a claim number",
                severity="error",
                policy_required=False,
            )
        )

    lines = data.get("line_items") or []

    # Arithmetic: line totals sum to the printed subtotal. Real Xactimate RCV then
    # adds overhead, profit, and material sales tax when those components are present.
    try:
        computed = sum(Decimal(str(item.get("total", "0"))) for item in lines)
        printed_line_total = data.get("line_item_total")
        subtotal = (
            Decimal(str(printed_line_total))
            if printed_line_total is not None
            else computed
        )
        if (
            lines
            and printed_line_total is not None
            and abs(computed - subtotal) > Decimal("1.00")
        ):
            failures.append(
                ValidationFailure(
                    field="line_item_total",
                    rule="arithmetic",
                    reason=(
                        f"Line items sum ${computed:.2f} does not match printed line-item "
                        f"total ${subtotal:.2f}"
                    ),
                    severity="warning",
                    policy_required=True,
                    machine_value=f"${computed:.2f}",
                    expected_value=f"${subtotal:.2f}",
                )
            )
        additions = sum(
            Decimal(str(data[field]))
            for field in ("overhead", "profit", "material_sales_tax")
            if data.get(field) is not None
        )
        rcv = Decimal(str(data.get("total_replacement_cost", "0")))
        # Nothing extracted to reconcile against (no line items, no printed subtotal, no
        # overhead/profit/tax) — treating that as "$0" would flag every RCV as a false
        # arithmetic mismatch instead of recognizing there's no basis for the check.
        has_reconciliation_basis = (
            bool(lines) or printed_line_total is not None or additions > 0
        )
        if (
            has_reconciliation_basis
            and rcv > 0
            and abs((subtotal + additions) - rcv) > Decimal("1.00")
        ):
            failures.append(
                ValidationFailure(
                    field="total_replacement_cost",
                    rule="arithmetic",
                    reason=(
                        f"Line subtotal plus overhead, profit, and tax "
                        f"${subtotal + additions:.2f} does not match RCV ${rcv:.2f}"
                    ),
                    severity="warning",
                    policy_required=True,
                    machine_value=f"${subtotal + additions:.2f}",
                    expected_value=f"${rcv:.2f}",
                )
            )
    except InvalidOperation:
        failures.append(
            ValidationFailure(
                field="total_replacement_cost",
                rule="arithmetic",
                reason="Could not parse amount as decimal",
                severity="warning",
                policy_required=False,
            )
        )

    # ACV = RCV - depreciation
    try:
        rcv = Decimal(str(data.get("total_replacement_cost", "0")))
        dep = Decimal(str(data.get("depreciation", "0")))
        acv = Decimal(str(data.get("actual_cash_value", "0")))
        if rcv > 0 and abs((rcv - dep) - acv) > Decimal("1.00"):
            failures.append(
                ValidationFailure(
                    field="actual_cash_value",
                    rule="acv_check",
                    reason=f"ACV ${acv:.2f} does not equal RCV ${rcv:.2f} minus depreciation ${dep:.2f}",
                    severity="warning",
                    policy_required=True,
                    machine_value=f"${acv:.2f}",
                    expected_value=f"${(rcv - dep):.2f}",
                )
            )
    except InvalidOperation:
        pass

    # Date of loss not in future
    dol = _parse_date(data.get("date_of_loss", ""))
    if dol and dol > date.today():
        failures.append(
            ValidationFailure(
                field="date_of_loss",
                rule="date_window",
                reason="Date of loss is in the future",
                severity="error",
                policy_required=False,
            )
        )

    # Positive amounts
    for field in ("total_replacement_cost", "actual_cash_value"):
        val = data.get(field)
        try:
            if val is not None and float(val) < 0:
                failures.append(
                    ValidationFailure(
                        field=field,
                        rule="negative_amount",
                        reason=f"{field} cannot be negative",
                        severity="error",
                        policy_required=True,
                    )
                )
        except (TypeError, ValueError):
            pass

    return failures


_SUPPORTING_TYPES = {
    "loss_report": {
        "loss report",
        "date of loss",
        "cause of loss",
        "first notice of loss",
    },
    "contractor_invoice": {
        "contractor invoice",
        "labor and materials",
        "invoice for repairs",
    },
    "adjuster_notes": {
        "adjuster notes",
        "field adjuster",
        "claim inspection",
        "adjuster assigned",
    },
    # Classification-only — recognized and routed for manual triage, no extraction pipeline.
    "roof_inspection_report": {
        "roof inspection",
        "roof condition report",
        "roof certification",
    },
    "damage_photo": {
        "photo log",
        "damage photo",
        "photograph attached",
    },  # see README: needs VLM for real reasoning
    "material_receipt": {"receipt", "material invoice", "purchase receipt"},
    "fire_report": {"fire department report", "fire incident report", "fire marshal"},
    "police_report": {
        "police report",
        "incident report number",
        "law enforcement report",
    },
}

PROPERTY = Domain(
    doc_type="xactimate",
    keywords={
        "xactimate",
        "property damage estimate",
        "replacement cost value",
        "actual cash value",
    },
    spec=_SPEC,
    validate=_validate,
    supporting_types=_SUPPORTING_TYPES,
    display_name="Property Insurance (Xactimate)",
    policy_collection="property",
    question_templates={
        "arithmetic": "What is the policy on line-item total discrepancies in property estimates? {reason}",
        "acv_check": "What is the policy when actual cash value does not equal RCV minus depreciation? {reason}",
        "negative_amount": "What is the policy when a claim amount is negative? {reason}",
    },
    client_name_field="insured_name",
)

register(PROPERTY)


class DeclarationsPage(BaseExtraction):
    insured_name: str = Field(description="Named insured on the policy")
    insured_address: str | None = Field(
        default=None, description="Named insured's mailing address"
    )
    policy_number: str | None = Field(
        default=None, description="Policy number; null if the field is blank"
    )
    policy_period_start: str | None = Field(
        default=None, description="Policy period start date MMDDYYYY"
    )
    policy_period_end: str | None = Field(
        default=None, description="Policy period end date MMDDYYYY"
    )
    coverage_a_dwelling: float | None = Field(
        default=None, description="Coverage A — dwelling limit"
    )
    coverage_b_other_structures: float | None = Field(
        default=None, description="Coverage B — other structures limit"
    )
    coverage_c_personal_property: float | None = Field(
        default=None, description="Coverage C — personal property limit"
    )
    coverage_d_loss_of_use: float | None = Field(
        default=None, description="Coverage D — loss of use limit"
    )
    deductible_all_other_perils: float | None = Field(
        default=None, description="All-other-perils deductible"
    )
    deductible_hurricane: float | None = Field(
        default=None, description="Hurricane/named-storm deductible"
    )
    premium_total: float | None = Field(
        default=None, description="Total policy premium"
    )
    mortgagee: str | None = Field(
        default=None, description="Mortgagee/lienholder name if listed"
    )
    carrier_name: str | None = Field(default=None, description="Insurance carrier name")
    agent_name: str | None = Field(
        default=None, description="Producing agent/agency name"
    )


_DECLARATIONS_SPEC = SchemaSpec(
    name="declarations_page",
    model=DeclarationsPage,
    system_prompt=_DECLARATIONS_PROMPT,
)

_DECLARATIONS_MANDATORY = ["insured_name", "policy_period_start", "policy_period_end"]


def _validate_declarations(data: dict) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for field in _DECLARATIONS_MANDATORY:
        val = data.get(field)
        if not val:
            failures.append(
                ValidationFailure(
                    field=field,
                    rule="mandatory",
                    reason=f"{field} is required but missing or empty",
                    severity="error",
                    policy_required=False,
                )
            )

    policy_number = data.get("policy_number")
    if policy_number and not re.search(r"\d", str(policy_number)):
        failures.append(
            ValidationFailure(
                field="policy_number",
                rule="mandatory",
                reason=f"'{policy_number}' has no digits — looks like a placeholder, not a policy number",
                severity="error",
                policy_required=False,
            )
        )

    start = _parse_date(data.get("policy_period_start") or "")
    end = _parse_date(data.get("policy_period_end") or "")
    if start and end and start > end:
        failures.append(
            ValidationFailure(
                field="policy_period_start",
                rule="date_window",
                reason=f"Policy period start {data['policy_period_start']} is after end {data['policy_period_end']}",
                severity="warning",
                policy_required=False,
            )
        )

    # Cross-document check (date_of_loss falling inside this policy's period) only runs when
    # a caller has merged that field in from the claim document — this domain's own extraction
    # is a single, standalone document, so date_of_loss isn't present unless explicitly merged.
    date_of_loss = _parse_date(data.get("date_of_loss") or "")
    if date_of_loss and start and end and not (start <= date_of_loss <= end):
        failures.append(
            ValidationFailure(
                field="date_of_loss",
                rule="date_window",
                reason=f"Date of loss {data['date_of_loss']} falls outside the policy period",
                severity="warning",
                policy_required=False,
            )
        )

    # Same cross-document caveat as above — property_address is only present if merged in.
    property_address = data.get("property_address")
    insured_address = data.get("insured_address")
    if (
        property_address
        and insured_address
        and fuzz.ratio(str(property_address), str(insured_address)) < 70
    ):
        failures.append(
            ValidationFailure(
                field="insured_address",
                rule="address_consistency",
                reason=f"Claim property address '{property_address}' does not fuzzy-match insured address '{insured_address}'",
                severity="warning",
                policy_required=False,
                machine_value=str(insured_address),
                expected_value=str(property_address),
            )
        )

    for field in (
        "coverage_a_dwelling",
        "coverage_b_other_structures",
        "coverage_c_personal_property",
        "coverage_d_loss_of_use",
        "deductible_all_other_perils",
        "deductible_hurricane",
        "premium_total",
    ):
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

    return failures


DECLARATIONS_PAGE = Domain(
    doc_type="declarations_page",
    keywords={"declarations page", "policy declarations", "insurance declarations"},
    spec=_DECLARATIONS_SPEC,
    validate=_validate_declarations,
    display_name="Insurance Declarations Page",
    policy_collection="property",
    client_name_field="insured_name",
)
register(DECLARATIONS_PAGE)
