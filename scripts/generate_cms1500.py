"""Generate synthetic CMS-1500 PDFs with ground truth for eval.

Run: uv run python scripts/generate_cms1500.py --count 30 --out data/synthetic
"""
import argparse
import json
import random
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF

random.seed(42)

VALID_ICD10 = ["J06.9", "Z00.00", "I10", "E11.9", "M54.5", "J18.9", "K92.1", "N39.0"]
VALID_CPT = ["99213", "99214", "99215", "99203", "99204", "71046", "80053", "93000"]
PLACES = ["11", "22", "23", "24"]

FIRST_NAMES = ["JOHN", "JANE", "ROBERT", "MARY", "JAMES", "PATRICIA", "MICHAEL", "LINDA"]
LAST_NAMES = ["DOE", "SMITH", "JONES", "WILLIAMS", "BROWN", "DAVIS", "MILLER", "WILSON"]
PROVIDER_NAMES = ["SMITH MD JANE", "JONES MD ROBERT", "BROWN MD ALICE", "DAVIS MD MARK"]
NPIS = ["1234567890", "0987654321", "1122334455", "5544332211"]


@dataclass
class ClaimData:
    insurance_id: str
    patient_name: str
    patient_dob: str
    patient_sex: str
    insured_name: str
    diagnosis_codes: list
    service_lines: list  # list of dicts
    billing_provider_name: str
    billing_provider_npi: str
    billing_provider_address: str
    total_charge: str
    amount_paid: str
    federal_tax_id: str
    accept_assignment: bool
    signature_on_file: bool
    # injected errors
    errors: list  # [{field, rule}]


def _random_date(year_range=(2025, 2026)) -> str:
    y = random.randint(*year_range)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{m:02d}{d:02d}{y}"


def _random_dob() -> str:
    y = random.randint(1950, 2000)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{m:02d}{d:02d}{y}"


def _make_claim(error_types: list[str]) -> ClaimData:
    n_lines = random.randint(1, 3)
    lines = []
    total = Decimal("0.00")
    dos = _random_date()
    codes = random.sample(VALID_ICD10, random.randint(1, 3))
    for _ in range(n_lines):
        charge = Decimal(str(random.randint(50, 500)))
        total += charge
        lines.append({
            "cpt_code": random.choice(VALID_CPT),
            "date_of_service": dos,
            "place_of_service": random.choice(PLACES),
            "diagnosis_pointer": "A",
            "charges": str(charge),
            "units": 1,
        })

    errors = []
    npi = random.choice(NPIS)
    billing_name = random.choice(PROVIDER_NAMES)
    insurance_id = f"INS{random.randint(100000000, 999999999)}"
    patient_name = f"{random.choice(LAST_NAMES)} {random.choice(FIRST_NAMES)}"
    dob = _random_dob()
    sex = random.choice(["M", "F"])
    tax_id = f"{random.randint(100000000, 999999999)}"

    # Inject errors
    if "missing_npi" in error_types:
        npi = ""
        errors.append({"field": "billing_provider_npi", "rule": "mandatory"})

    if "invalid_icd10" in error_types:
        codes[0] = "XXXXX"
        errors.append({"field": "diagnosis_codes", "rule": "icd10_lookup"})

    if "arithmetic_mismatch" in error_types:
        total = total + Decimal("10.00")
        errors.append({"field": "total_charge", "rule": "arithmetic"})

    if "missing_insurance_id" in error_types:
        insurance_id = ""
        errors.append({"field": "insurance_id", "rule": "mandatory"})

    if "invalid_cpt" in error_types:
        lines[0]["cpt_code"] = "00000"
        errors.append({"field": "service_lines", "rule": "cpt_lookup"})

    return ClaimData(
        insurance_id=insurance_id,
        patient_name=patient_name,
        patient_dob=dob,
        patient_sex=sex,
        insured_name=patient_name,
        diagnosis_codes=codes,
        service_lines=lines,
        billing_provider_name=billing_name,
        billing_provider_npi=npi,
        billing_provider_address=f"{random.randint(100,999)} MAIN ST CITY ST {random.randint(10000,99999)}",
        total_charge=str(total),
        amount_paid="0.00",
        federal_tax_id=tax_id,
        accept_assignment=True,
        signature_on_file=True,
        errors=errors,
    )


def _render_pdf(claim: ClaimData, out_path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    def row(label: str, value: str) -> None:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(60, 6, label, border=0)
        pdf.set_font("Helvetica", size=9)
        pdf.cell(0, 6, str(value), border=0, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "HEALTH INSURANCE CLAIM FORM CMS-1500", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(3)

    row("Box 1a - Insured ID:", claim.insurance_id)
    row("Box 2 - Patient Name:", claim.patient_name)
    row("Box 3 - Patient DOB:", claim.patient_dob)
    row("Box 3 - Sex:", claim.patient_sex)
    row("Box 4 - Insured Name:", claim.insured_name)
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Box 21 - Diagnosis Codes (ICD-10-CM):", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    for i, code in enumerate(claim.diagnosis_codes):
        pdf.cell(0, 5, f"  {chr(65+i)}. {code}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Box 24 - Service Lines:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    for i, line in enumerate(claim.service_lines, 1):
        pdf.cell(0, 5,
            f"  Line {i}: DOS {line['date_of_service']} | POS {line['place_of_service']} | "
            f"CPT {line['cpt_code']} | Dx {line['diagnosis_pointer']} | "
            f"${line['charges']} | Units {line['units']}",
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(3)

    row("Box 25 - Federal Tax ID:", claim.federal_tax_id)
    row("Box 27 - Accept Assignment:", "YES" if claim.accept_assignment else "NO")
    row("Box 28 - Total Charge:", f"${claim.total_charge}")
    row("Box 29 - Amount Paid:", f"${claim.amount_paid}")
    pdf.ln(3)
    row("Box 31 - Signature on File:", "YES" if claim.signature_on_file else "NO")
    pdf.ln(3)
    row("Box 33 - Billing Provider:", claim.billing_provider_name)
    row("Box 33a - Billing NPI:", claim.billing_provider_npi)
    row("Box 33 - Address:", claim.billing_provider_address)

    pdf.output(str(out_path))


ERROR_POOL = [
    [],  # clean claim
    [],  # clean claim
    [],  # clean claim
    ["missing_npi"],
    ["invalid_icd10"],
    ["arithmetic_mismatch"],
    ["missing_insurance_id"],
    ["invalid_cpt"],
    ["missing_npi", "invalid_icd10"],
    ["arithmetic_mismatch", "invalid_cpt"],
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for i in range(args.count):
        error_types = ERROR_POOL[i % len(ERROR_POOL)]
        claim = _make_claim(error_types)
        pkg_dir = args.out / f"package_{i:03d}"
        pkg_dir.mkdir(exist_ok=True)
        _render_pdf(claim, pkg_dir / "claim.pdf")
        gt = {"fields": asdict(claim), "errors": claim.errors}
        (pkg_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

    print(f"Generated {args.count} packages in {args.out}")


if __name__ == "__main__":
    main()
