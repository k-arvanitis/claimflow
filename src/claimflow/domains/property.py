from datetime import date
from decimal import Decimal, InvalidOperation

from claimflow.domains.base import Domain, register
from claimflow.state import ValidationFailure
from doc_intel.schemas.base import BaseExtraction, SchemaSpec
from pydantic import Field


class LineItem(BaseExtraction):
    category: str = Field(description="Work category (e.g. Roofing, Drywall)")
    description: str = Field(description="Line item description")
    quantity: float = Field(description="Quantity")
    unit: str = Field(description="Unit of measure (SF, LF, EA, HR)")
    unit_cost: float = Field(description="Unit cost in dollars")
    total: float = Field(description="Line total = quantity × unit_cost")


class XactimatePDF(BaseExtraction):
    claim_number: str = Field(description="Insurance claim number")
    insured_name: str = Field(description="Name of insured property owner")
    property_address: str = Field(description="Full address of damaged property")
    date_of_loss: str = Field(description="Date of loss MMDDYYYY")
    cause_of_loss: str = Field(description="Cause of loss (e.g. Wind, Water, Fire)")
    adjuster_name: str | None = Field(default=None, description="Name of claims adjuster")
    line_items: list[LineItem] = Field(description="Itemized repair/replacement line items")
    total_replacement_cost: float = Field(description="Total replacement cost value (RCV)")
    depreciation: float = Field(description="Total depreciation amount")
    actual_cash_value: float = Field(description="Actual cash value = RCV minus depreciation")
    deductible: float | None = Field(default=None, description="Policy deductible amount")


_SPEC = SchemaSpec(
    name="xactimate",
    model=XactimatePDF,
    system_prompt=(
        "Extract all fields from this Xactimate property damage estimate. "
        "Line items each have a category, description, quantity, unit, unit cost, and total. "
        "RCV = total replacement cost value. ACV = RCV minus depreciation. "
        "For dates use MMDDYYYY format."
    ),
)

_MANDATORY = [
    "claim_number", "insured_name", "property_address",
    "date_of_loss", "cause_of_loss", "line_items", "total_replacement_cost",
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

    lines = data.get("line_items") or []

    # Arithmetic: line totals sum to RCV
    try:
        computed = sum(Decimal(str(item.get("total", "0"))) for item in lines)
        rcv = Decimal(str(data.get("total_replacement_cost", "0")))
        if rcv > 0 and abs(computed - rcv) > Decimal("1.00"):
            failures.append(ValidationFailure(field="total_replacement_cost", rule="arithmetic",
                reason=f"Line items sum ${computed:.2f} does not match RCV ${rcv:.2f}"))
    except InvalidOperation:
        failures.append(ValidationFailure(field="total_replacement_cost", rule="arithmetic",
            reason="Could not parse amount as decimal"))

    # ACV = RCV - depreciation
    try:
        rcv = Decimal(str(data.get("total_replacement_cost", "0")))
        dep = Decimal(str(data.get("depreciation", "0")))
        acv = Decimal(str(data.get("actual_cash_value", "0")))
        if rcv > 0 and abs((rcv - dep) - acv) > Decimal("1.00"):
            failures.append(ValidationFailure(field="actual_cash_value", rule="acv_check",
                reason=f"ACV ${acv:.2f} does not equal RCV ${rcv:.2f} minus depreciation ${dep:.2f}"))
    except InvalidOperation:
        pass

    # Date of loss not in future
    dol = _parse_date(data.get("date_of_loss", ""))
    if dol and dol > date.today():
        failures.append(ValidationFailure(field="date_of_loss", rule="date_window",
            reason="Date of loss is in the future"))

    # Positive amounts
    for field in ("total_replacement_cost", "actual_cash_value"):
        val = data.get(field)
        try:
            if val is not None and float(val) < 0:
                failures.append(ValidationFailure(field=field, rule="negative_amount",
                    reason=f"{field} cannot be negative"))
        except (TypeError, ValueError):
            pass

    return failures


PROPERTY = Domain(
    doc_type="xactimate",
    keywords={"xactimate", "property damage estimate", "replacement cost value", "actual cash value"},
    spec=_SPEC,
    validate=_validate,
)

register(PROPERTY)
