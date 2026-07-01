"""Generate synthetic SBA loan application PDFs with ground truth for eval.

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


def _render_pdf(loan: LoanData, out_path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    def row(label: str, value: str) -> None:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(70, 6, label, border=0)
        pdf.set_font("Helvetica", size=9)
        pdf.cell(0, 6, str(value), border=0, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "SBA LOAN APPLICATION", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)
    pdf.set_font("Helvetica", size=9)
    pdf.cell(0, 6, "Small Business Administration - Business Loan Application", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    row("Applicant Name:", loan.applicant_name)
    row("Business Name:", loan.business_name)
    row("Tax ID (EIN):", loan.tax_id)
    row("Loan Amount Requested:", f"${loan.loan_amount_requested}")
    row("Loan Purpose:", loan.loan_purpose)
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Financial Information:", new_x="LMARGIN", new_y="NEXT")
    row("Annual Gross Revenue:", f"${loan.gross_revenue}")
    row("Annual Net Income:", f"${loan.net_income}")
    row("Total Assets:", f"${loan.total_assets}")
    row("Total Liabilities:", f"${loan.total_liabilities}")
    pdf.ln(3)

    row("Applicant Signature on File:", "YES" if loan.signature_on_file else "NO")

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
