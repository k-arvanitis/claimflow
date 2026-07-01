"""Generate synthetic Xactimate property damage PDFs with ground truth for eval.

Run: uv run python scripts/generate_xactimate.py --count 30 --out data/synthetic/property
"""
import argparse
import json
import random
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF

random.seed(43)

CAUSES = ["Wind", "Water", "Fire", "Hail", "Vandalism", "Flood"]
CATEGORIES = ["Roofing", "Drywall", "Flooring", "Painting", "Electrical", "Plumbing", "Siding"]
UNITS = ["SF", "LF", "EA", "HR", "SQ"]
ADJUSTER_NAMES = ["ALICE JOHNSON", "BOB MARTINEZ", "CAROL SMITH", "DAN LEE"]
FIRST_NAMES = ["JAMES", "LINDA", "ROBERT", "MARY", "WILLIAM", "BARBARA"]
LAST_NAMES = ["TAYLOR", "ANDERSON", "THOMAS", "JACKSON", "WHITE", "HARRIS"]
STREETS = ["OAK ST", "MAPLE AVE", "ELM DR", "PINE RD", "CEDAR LN"]


@dataclass
class PropertyData:
    claim_number: str
    insured_name: str
    property_address: str
    date_of_loss: str
    cause_of_loss: str
    adjuster_name: str
    line_items: list
    total_replacement_cost: str
    depreciation: str
    actual_cash_value: str
    errors: list


def _random_date() -> str:
    y = random.randint(2024, 2025)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{m:02d}{d:02d}{y}"


def _make_claim(error_types: list[str]) -> PropertyData:
    n_items = random.randint(2, 5)
    items = []
    total = Decimal("0.00")
    for _ in range(n_items):
        qty = Decimal(str(random.randint(10, 500)))
        unit_cost = Decimal(str(random.randint(2, 50)))
        item_total = qty * unit_cost
        total += item_total
        items.append({
            "category": random.choice(CATEGORIES),
            "description": f"{random.choice(CATEGORIES)} repair",
            "quantity": float(qty),
            "unit": random.choice(UNITS),
            "unit_cost": float(unit_cost),
            "total": float(item_total),
        })

    dep_pct = Decimal(str(random.randint(5, 30))) / 100
    dep = (total * dep_pct).quantize(Decimal("0.01"))
    acv = total - dep
    claim_number = f"CLM{random.randint(1000000, 9999999)}"
    insured = f"{random.choice(LAST_NAMES)} {random.choice(FIRST_NAMES)}"
    address = f"{random.randint(100, 9999)} {random.choice(STREETS)} CITY ST {random.randint(10000, 99999)}"

    errors = []

    if "arithmetic_mismatch" in error_types:
        total = total + Decimal("50.00")
        errors.append({"field": "total_replacement_cost", "rule": "arithmetic"})

    if "acv_mismatch" in error_types:
        acv = acv - Decimal("100.00")
        errors.append({"field": "actual_cash_value", "rule": "acv_check"})

    if "missing_claim_number" in error_types:
        claim_number = ""
        errors.append({"field": "claim_number", "rule": "mandatory"})

    if "negative_amount" in error_types:
        acv = Decimal("-50.00")
        errors.append({"field": "actual_cash_value", "rule": "negative_amount"})

    return PropertyData(
        claim_number=claim_number,
        insured_name=insured,
        property_address=address,
        date_of_loss=_random_date(),
        cause_of_loss=random.choice(CAUSES),
        adjuster_name=random.choice(ADJUSTER_NAMES),
        line_items=items,
        total_replacement_cost=str(total),
        depreciation=str(dep),
        actual_cash_value=str(acv),
        errors=errors,
    )


def _render_pdf(claim: PropertyData, out_path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    def row(label: str, value: str) -> None:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(70, 6, label, border=0)
        pdf.set_font("Helvetica", size=9)
        pdf.cell(0, 6, str(value), border=0, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "XACTIMATE PROPERTY DAMAGE ESTIMATE", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)
    pdf.set_font("Helvetica", size=9)
    pdf.cell(0, 6, "Replacement Cost Value Estimate", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    row("Claim Number:", claim.claim_number)
    row("Insured Name:", claim.insured_name)
    row("Property Address:", claim.property_address)
    row("Date of Loss:", claim.date_of_loss)
    row("Cause of Loss:", claim.cause_of_loss)
    row("Adjuster:", claim.adjuster_name)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Line Items:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=8)
    for item in claim.line_items:
        pdf.cell(0, 5,
            f"  [{item['category']}] {item['description']} | "
            f"Qty: {item['quantity']} {item['unit']} | "
            f"@ ${item['unit_cost']:.2f} | Total: ${item['total']:.2f}",
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(4)

    row("Total Replacement Cost Value (RCV):", f"${claim.total_replacement_cost}")
    row("Depreciation:", f"${claim.depreciation}")
    row("Actual Cash Value (ACV):", f"${claim.actual_cash_value}")

    pdf.output(str(out_path))


ERROR_POOL = [
    [],
    [],
    [],
    ["arithmetic_mismatch"],
    ["acv_mismatch"],
    ["missing_claim_number"],
    ["negative_amount"],
    ["arithmetic_mismatch", "acv_mismatch"],
    [],
    ["acv_mismatch"],
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic/property"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for i in range(args.count):
        error_types = ERROR_POOL[i % len(ERROR_POOL)]
        claim = _make_claim(error_types)
        pkg_dir = args.out / f"package_{i:03d}"
        pkg_dir.mkdir(exist_ok=True)
        _render_pdf(claim, pkg_dir / "estimate.pdf")
        gt = {"domain": "xactimate", "fields": asdict(claim), "errors": claim.errors}
        (pkg_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

    print(f"Generated {args.count} packages in {args.out}")


if __name__ == "__main__":
    main()
