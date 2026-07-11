"""Generate synthetic SBA 7(a) loan application PDFs with ground truth for eval.

Visually replicates a bank Loan Request Form (grid layout, entity-type
checkboxes, ownership block) plus a financial summary block styled after
SBA Form 413's Assets/Liabilities section.

Run: uv run python scripts/generate_loan.py --count 30 --out data/synthetic/loan
"""
import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from fpdf import FPDF

random.seed(44)

PURPOSES = [
    "Working capital", "Equipment purchase", "Commercial real estate",
    "Business expansion", "Inventory financing", "Debt refinancing",
]
BUSINESS_TYPES = ["LLC", "Inc", "Corp", "DBA", "Partnership"]
FIRST_NAMES = ["MICHAEL", "SARAH", "DAVID", "JENNIFER", "CHRISTOPHER", "AMANDA"]
LAST_NAMES = ["GARCIA", "RODRIGUEZ", "MARTINEZ", "HERNANDEZ", "LOPEZ", "GONZALEZ"]
BUSINESS_WORDS = ["SOLUTIONS", "ENTERPRISES", "GROUP", "SERVICES", "INDUSTRIES"]

ENTITY_LABELS = ["Corporation", "Sole Proprietorship", "Limited Liability Company", "Partnership or Limited Partnership"]
ENTITY_MAP = {
    "LLC": "Limited Liability Company",
    "Inc": "Corporation",
    "Corp": "Corporation",
    "DBA": "Sole Proprietorship",
    "Partnership": "Partnership or Limited Partnership",
}


@dataclass
class LoanData:
    applicant_name: str
    business_name: str
    tax_id: str
    loan_amount_requested: str
    loan_purpose: str
    gross_revenue: str
    net_income: str
    total_assets: str
    total_liabilities: str
    signature_on_file: bool
    errors: list


def _make_loan(error_types: list[str]) -> LoanData:
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    applicant = f"{first} {last}"
    biz = f"{last} {random.choice(BUSINESS_WORDS)} {random.choice(BUSINESS_TYPES)}"
    ein_a = random.randint(10, 99)
    ein_b = random.randint(1000000, 9999999)
    tax_id = f"{ein_a}-{ein_b}"

    gross = random.randint(200000, 2000000)
    net = int(gross * random.uniform(0.05, 0.30))
    assets = random.randint(100000, 1000000)
    liabilities = int(assets * random.uniform(0.2, 0.7))
    loan_amt = random.randint(50000, 500000)

    errors = []

    if "missing_tax_id" in error_types:
        tax_id = ""
        errors.append({"field": "tax_id", "rule": "mandatory"})

    if "zero_loan_amount" in error_types:
        loan_amt = 0
        errors.append({"field": "loan_amount_requested", "rule": "positive_amount"})

    if "income_inconsistency" in error_types:
        net = gross + random.randint(10000, 50000)
        errors.append({"field": "net_income", "rule": "income_consistency"})

    if "missing_signature" in error_types:
        sig = False
        errors.append({"field": "signature_on_file", "rule": "signature_required"})
    else:
        sig = True

    if "missing_applicant" in error_types:
        applicant = ""
        errors.append({"field": "applicant_name", "rule": "mandatory"})

    return LoanData(
        applicant_name=applicant,
        business_name=biz,
        tax_id=tax_id,
        loan_amount_requested=str(loan_amt),
        loan_purpose=random.choice(PURPOSES),
        gross_revenue=str(gross),
        net_income=str(net),
        total_assets=str(assets),
        total_liabilities=str(liabilities),
        signature_on_file=sig,
        errors=errors,
    )


# ─── PDF RENDERER ─────────────────────────────────────────────────────────────

L = 14.0
R = 201.0
W = R - L


def _render_pdf(loan: LoanData, out_path: Path) -> None:  # noqa: C901
    pdf = FPDF(format="letter")
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.add_page()

    def _wrap(text: str, w: float, size: float) -> list[str]:
        pdf.set_font("Helvetica", "B", size)
        words = text.split(" ")
        lines: list[str] = []
        cur = ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if pdf.get_string_width(trial) <= w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def lbl(x: float, y: float, text: str, w: float, size: float = 6.0) -> None:
        line_h = size * 0.42
        for i, line in enumerate(_wrap(text, w - 2, size)):
            pdf.set_xy(x + 1, y + 0.8 + i * line_h)
            pdf.cell(w - 2, line_h, line, border=0)

    def val(x: float, y: float, text: str, w: float, size: float = 9) -> None:
        pdf.set_xy(x + 1, y + 5.2)
        pdf.set_font("Helvetica", "", size)
        pdf.cell(w - 2, 5, str(text), border=0)

    def hln(x1: float, y: float, x2: float) -> None:
        pdf.line(x1, y, x2, y)

    def vln(x: float, y1: float, y2: float) -> None:
        pdf.line(x, y1, x, y2)

    def bx(x: float, y: float, bw: float, bh: float) -> None:
        pdf.rect(x, y, bw, bh)

    def grid(x: float, y: float, w: float, h: float, cols: list[float]) -> None:
        """Draw an outer box plus internal vertical lines at cumulative col offsets."""
        bx(x, y, w, h)
        for off in cols:
            vln(x + off, y, y + h)

    # ── header ────────────────────────────────────────────────────────────────
    pdf.set_xy(L, 12)
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(120, 9, "LOAN REQUEST FORM", border=0)

    pdf.set_xy(R - 70, 13)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(70, 5, "HORIZON COMMUNITY BANK", align="R", border=0)
    pdf.set_xy(R - 70, 18.5)
    pdf.set_font("Helvetica", "", 6)
    pdf.cell(70, 4, "Member FDIC  |  Equal Housing Lender", align="R", border=0)

    hln(L, 26, R)

    # ── loan amount line ─────────────────────────────────────────────────────
    y = 31
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(88, 6, "The undersigned hereby make request for a loan of", border=0)

    amt_x = L + 89
    bx(amt_x, y - 1, 38, 7)
    pdf.set_xy(amt_x + 2, y - 1)
    pdf.set_font("Helvetica", "", 6)
    pdf.cell(4, 7, "$", border=0)
    pdf.set_xy(amt_x + 6, y + 0.5)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(30, 5, f"{int(loan.loan_amount_requested):,}" if loan.loan_amount_requested else "", border=0)

    pdf.set_xy(amt_x + 40, y)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(22, 6, "repayable in", border=0)
    bx(amt_x + 62, y - 1, 14, 7)
    pdf.set_xy(amt_x + 77, y)
    pdf.cell(40, 6, "monthly installments", border=0)

    # ── APPLICANT COMPANY ────────────────────────────────────────────────────
    y = 44
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(80, 5, "APPLICANT COMPANY", border=0)

    entity = ENTITY_MAP.get(loan.business_name.split()[-1], "")
    y += 6
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.cell(24, 5, "Please check one:", border=0)
    cx = L + 25
    for option in ENTITY_LABELS:
        mark = "X" if option == entity else " "
        pdf.rect(cx, y + 0.5, 3, 3)
        pdf.set_xy(cx, y + 0.4)
        pdf.set_font("Helvetica", "B", 6)
        pdf.cell(3, 3, mark, align="C", border=0)
        pdf.set_xy(cx + 4, y)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.cell(pdf.get_string_width(option) + 3, 5, option, border=0)
        cx += 4 + pdf.get_string_width(option) + 6

    # applicant company grid: 3 rows
    y += 6
    row_h = 11.0
    box_h = row_h * 3
    grid(L, y, W, box_h, [95, 148])
    hln(L, y + row_h, R)
    hln(L, y + 2 * row_h, R)

    lbl(L, y, "Name of Company", 95)
    val(L, y, loan.business_name, 95, size=8)
    lbl(L + 95, y, "Nature of Business", 53)
    val(L + 95, y, loan.loan_purpose, 53, size=7.5)
    lbl(L + 148, y, "Date Established", R - L - 148)

    y2 = y + row_h
    lbl(L, y2, "Business Address (No. & Street, City, State, Zip Code)", 148)
    lbl(L + 148, y2, "Tax ID Number", R - L - 148)
    val(L + 148, y2, loan.tax_id, R - L - 148, size=8)

    y3 = y2 + row_h
    lbl(L, y3, "Telephone Number", 62)
    lbl(L + 62, y3, "Email Address", 62)
    lbl(L + 124, y3, "State of Incorporation", R - L - 124)
    vln(L + 62, y3, y3 + row_h)
    vln(L + 124, y3, y3 + row_h)

    # ── OWNERSHIP OF APPLICANT COMPANY ───────────────────────────────────────
    y = y + box_h + 6
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(120, 5, "OWNERSHIP OF APPLICANT COMPANY", border=0)
    y += 5
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(W, 4, "List below all owners, partners, LLC members and shareholders totaling 100% ownership", border=0)

    y += 5
    own_h = row_h * 2
    grid(L, y, W, own_h, [95, 148])
    hln(L, y + row_h, R)

    lbl(L, y, "Principal 1 - Name", 95)
    val(L, y, loan.applicant_name, 95, size=8)
    lbl(L + 95, y, "Ownership Percentage", 53)
    val(L + 95, y, "100%", 53, size=8)
    lbl(L + 148, y, "Title", R - L - 148)
    val(L + 148, y, "Owner", R - L - 148, size=8)

    y2 = y + row_h
    lbl(L, y2, "Address (No. & Street, City, State, Zip Code)", 148)
    lbl(L + 148, y2, "Social Security Number", R - L - 148)

    # ── BUSINESS FINANCIAL SUMMARY ───────────────────────────────────────────
    y = y + own_h + 6
    pdf.set_fill_color(225, 225, 225)
    pdf.rect(L, y, W, 6, style="F")
    pdf.rect(L, y, W, 6)
    pdf.set_xy(L + 1, y + 1)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(W - 2, 4, "BUSINESS FINANCIAL SUMMARY", border=0)

    y += 6
    fin_h = row_h * 2
    half = W / 2
    grid(L, y, W, fin_h, [half])
    hln(L, y + row_h, R)

    lbl(L, y, "Annual Gross Revenue", half)
    val(L, y, f"$ {int(loan.gross_revenue):,}" if loan.gross_revenue else "", half, size=9)
    lbl(L + half, y, "Annual Net Income", half)
    val(L + half, y, f"$ {int(loan.net_income):,}" if loan.net_income else "", half, size=9)

    y2 = y + row_h
    lbl(L, y2, "Total Assets", half)
    val(L, y2, f"$ {int(loan.total_assets):,}" if loan.total_assets else "", half, size=9)
    lbl(L + half, y2, "Total Liabilities", half)
    val(L + half, y2, f"$ {int(loan.total_liabilities):,}" if loan.total_liabilities else "", half, size=9)

    y = y + fin_h
    tot_h = 12.0
    bx(L, y, W, tot_h)
    lbl(L, y, "Total Loan Requested for Project", W)
    pdf.set_xy(L + 1, y + 5.5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(W - 2, 5, f"$ {int(loan.loan_amount_requested):,}" if loan.loan_amount_requested else "", border=0)

    # ── certification + signature ────────────────────────────────────────────
    y = y + tot_h + 8
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "", 7.5)
    cert = (
        "The undersigned (applicant) represents, warrants, and affirms that the statements made in this "
        "application, and any accompanying financial statements, are true and correct to the best of the "
        "undersigned's knowledge, and authorizes Horizon Community Bank to make inquiries as necessary to "
        "verify the accuracy of the information provided and to determine creditworthiness."
    )
    pdf.multi_cell(W, 3.8, cert, border=0)

    y = pdf.get_y() + 10
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "", 9)
    sig_text = "Signature on File" if loan.signature_on_file else ""
    pdf.cell(15, 6, "SIGNED:", border=0)
    pdf.set_xy(L + 16, y)
    hln(L + 16, y + 5, L + 100)
    pdf.set_xy(L + 18, y - 1.5)
    pdf.cell(80, 6, sig_text, border=0)

    pdf.set_xy(L + 110, y)
    pdf.cell(12, 6, "DATE:", border=0)
    hln(L + 122, y + 5, L + 170)

    pdf.output(str(out_path))


ERROR_POOL = [
    [],
    [],
    [],
    ["missing_tax_id"],
    ["zero_loan_amount"],
    ["income_inconsistency"],
    ["missing_signature"],
    ["missing_applicant"],
    ["missing_tax_id", "income_inconsistency"],
    ["zero_loan_amount", "missing_signature"],
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic/loan"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for i in range(args.count):
        error_types = ERROR_POOL[i % len(ERROR_POOL)]
        loan = _make_loan(error_types)
        pkg_dir = args.out / f"package_{i:03d}"
        pkg_dir.mkdir(exist_ok=True)
        _render_pdf(loan, pkg_dir / "application.pdf")
        gt = {"domain": "loan", "fields": asdict(loan), "errors": loan.errors}
        (pkg_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

    print(f"Generated {args.count} packages in {args.out}")


if __name__ == "__main__":
    main()
