"""Generate synthetic Xactimate property damage PDFs with ground truth for eval.

Visually replicates a Xactimate-style estimate report: claim info grid,
line item detail table, and an RCV/Depreciation/ACV totals block.

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
CITIES = ["SPRINGFIELD", "RIVERSIDE", "GREENVILLE", "FAIRVIEW", "MADISON"]
STATES = ["IL", "CA", "NC", "TX", "WI", "NY"]


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
    address = f"{random.randint(100, 9999)} {random.choice(STREETS)}, {random.choice(CITIES)}, {random.choice(STATES)} {random.randint(10000, 99999)}"

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


# ─── PDF RENDERER ─────────────────────────────────────────────────────────────

L = 14.0
R = 201.0
W = R - L


def _render_pdf(claim: PropertyData, out_path: Path) -> None:  # noqa: C901
    pdf = FPDF(format="letter")
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.add_page()

    def hln(x1: float, y: float, x2: float) -> None:
        pdf.line(x1, y, x2, y)

    def vln(x: float, y1: float, y2: float) -> None:
        pdf.line(x, y1, x, y2)

    def bx(x: float, y: float, bw: float, bh: float) -> None:
        pdf.rect(x, y, bw, bh)

    def lbl(x: float, y: float, text: str, size: float = 6.5) -> None:
        pdf.set_xy(x + 1, y + 0.8)
        pdf.set_font("Helvetica", "B", size)
        pdf.cell(0, 3, text, border=0)

    def val(x: float, y: float, text: str, w: float, size: float = 9) -> None:
        pdf.set_xy(x + 1, y + 4.8)
        pdf.set_font("Helvetica", "", size)
        pdf.cell(w - 2, 5, str(text), border=0)

    # ── header ────────────────────────────────────────────────────────────────
    pdf.set_xy(L, 12)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(W, 8, "PROPERTY DAMAGE ESTIMATE", align="C", border=0)
    pdf.set_xy(L, 20)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(W, 5, "Xactimate Format - Replacement Cost Value Estimate", align="C", border=0)
    hln(L, 27, R)

    # ── claim info grid: 4 rows x 2 cols ────────────────────────────────────
    y = 32
    row_h = 10.0
    box_h = row_h * 4
    half = W / 2

    bx(L, y, W, box_h)
    vln(L + half, y, y + box_h)
    for i in range(1, 4):
        hln(L, y + i * row_h, R)

    rows = [
        ("Insured", claim.insured_name, "Claim Number", claim.claim_number),
        ("Property Address", claim.property_address, "Date of Loss", claim.date_of_loss),
        ("Type of Loss", claim.cause_of_loss, "Price List", ""),
        ("Claim Rep. / Adjuster", claim.adjuster_name, "Estimate Completed", ""),
    ]
    for i, (l1, v1, l2, v2) in enumerate(rows):
        ry = y + i * row_h
        lbl(L, ry, l1)
        val(L, ry, v1, half, size=8.5)
        lbl(L + half, ry, l2)
        val(L + half, ry, v2, half, size=8.5)

    # ── line item detail table ───────────────────────────────────────────────
    y = y + box_h + 8
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(W, 5, "LINE ITEM DETAIL", border=0)
    y += 6

    cols = {
        "cat":  (L, 30),
        "desc": (L + 30, 62),
        "qty":  (L + 92, 22),
        "unit": (L + 114, 16),
        "cost": (L + 130, 26),
        "tot":  (L + 156, R - L - 156),
    }
    hdr_h = 7.0
    bx(L, y, W, hdr_h)
    for key, (cx, cw) in cols.items():
        if cx > L:
            vln(cx, y, y + hdr_h)
    headers = {"cat": "CATEGORY", "desc": "DESCRIPTION", "qty": "QTY", "unit": "UNIT", "cost": "UNIT COST", "tot": "TOTAL (RCV)"}
    for key, (cx, cw) in cols.items():
        pdf.set_xy(cx + 1, y + 1.8)
        pdf.set_font("Helvetica", "B", 6.5)
        pdf.cell(cw - 2, 3.5, headers[key], border=0)

    y += hdr_h
    line_h = 8.0
    for item in claim.line_items:
        bx(L, y, W, line_h)
        for key, (cx, cw) in cols.items():
            if cx > L:
                vln(cx, y, y + line_h)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(cols["cat"][0] + 1, y + 2.2)
        pdf.cell(cols["cat"][1] - 2, 4, item["category"], border=0)
        pdf.set_xy(cols["desc"][0] + 1, y + 2.2)
        pdf.cell(cols["desc"][1] - 2, 4, item["description"], border=0)
        pdf.set_xy(cols["qty"][0] + 1, y + 2.2)
        pdf.cell(cols["qty"][1] - 2, 4, f"{item['quantity']:g}", border=0)
        pdf.set_xy(cols["unit"][0] + 1, y + 2.2)
        pdf.cell(cols["unit"][1] - 2, 4, item["unit"], border=0)
        pdf.set_xy(cols["cost"][0] + 1, y + 2.2)
        pdf.cell(cols["cost"][1] - 2, 4, f"${item['unit_cost']:.2f}", border=0)
        pdf.set_xy(cols["tot"][0] + 1, y + 2.2)
        pdf.cell(cols["tot"][1] - 2, 4, f"${item['total']:.2f}", border=0)
        y += line_h

    # ── totals block ──────────────────────────────────────────────────────────
    y += 8
    tot_w = 85.0
    tot_x = R - tot_w
    tot_row_h = 8.0

    totals = [
        ("Total Replacement Cost Value (RCV)", f"$ {claim.total_replacement_cost}"),
        ("Less Depreciation", f"$ {claim.depreciation}"),
        ("Actual Cash Value (ACV)", f"$ {claim.actual_cash_value}"),
    ]
    bx(tot_x, y, tot_w, tot_row_h * len(totals))
    for i in range(1, len(totals)):
        hln(tot_x, y + i * tot_row_h, R)
    for i, (label, value) in enumerate(totals):
        ry = y + i * tot_row_h
        pdf.set_xy(tot_x + 1, ry + 1)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(tot_w - 30, 5, label, border=0)
        pdf.set_xy(tot_x + tot_w - 30, ry + 1)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(29, 5, value, align="R", border=0)

    # ── prepared-by line ──────────────────────────────────────────────────────
    y = y + tot_row_h * len(totals) + 12
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(60, 5, f"Prepared by: {claim.adjuster_name}", border=0)
    pdf.set_xy(L + 90, y)
    pdf.cell(60, 5, f"Date: {claim.date_of_loss[0:2]}/{claim.date_of_loss[2:4]}/{claim.date_of_loss[4:8]}", border=0)

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
