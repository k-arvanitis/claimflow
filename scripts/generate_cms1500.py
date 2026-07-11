"""Generate synthetic CMS-1500 PDFs that visually replicate the real form layout.

Run: uv run python scripts/generate_cms1500.py --count 30 --out data/synthetic/health
"""
import argparse
import json
import random
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF

random.seed(42)

VALID_ICD10 = [
    "J06.9", "Z00.00", "I10", "E11.9", "M54.50",
    "J18.9", "K92.1", "N39.0", "Z12.11", "F41.1",
    "G43.909", "R51.9", "J45.20", "K21.00", "M79.3",
]
VALID_CPT = [
    "99213", "99214", "99215", "99203", "99204",
    "71046", "80053", "93000", "36415", "85025",
    "99232", "97110", "90837", "99395", "81001",
]
PLACES = ["11", "22", "23", "24", "31"]
FIRST_NAMES = [
    "JOHN", "JANE", "ROBERT", "MARY", "JAMES", "PATRICIA",
    "MICHAEL", "LINDA", "DAVID", "BARBARA", "RICHARD", "SUSAN",
]
LAST_NAMES = [
    "DOE", "SMITH", "JONES", "WILLIAMS", "BROWN", "DAVIS",
    "MILLER", "WILSON", "MOORE", "TAYLOR", "ANDERSON", "THOMAS",
]
PROVIDER_NAMES = [
    "SMITH MD JANE", "JONES MD ROBERT", "BROWN MD ALICE",
    "DAVIS MD MARK", "JOHNSON MD LISA", "TAYLOR MD PETER",
]
NPIS = [
    "4827193650", "7062948513", "3951874620",
    "8264051937", "5738261490", "2946180375",
]
CITIES = ["SPRINGFIELD", "RIVERSIDE", "GREENVILLE", "FAIRVIEW", "MADISON", "OAKDALE"]
STATES = ["IL", "CA", "NC", "TX", "WI", "NY", "FL", "OH"]
STREETS = ["MAIN ST", "OAK AVE", "ELM DR", "PARK BLVD", "MAPLE LN", "CEDAR RD"]

ERROR_POOL = [
    [],
    [],
    [],
    ["missing_npi"],
    ["invalid_icd10"],
    ["arithmetic_mismatch"],
    ["missing_insurance_id"],
    ["invalid_cpt"],
    ["missing_npi", "invalid_icd10"],
    ["arithmetic_mismatch", "invalid_cpt"],
]


@dataclass
class ClaimData:
    insurance_id: str
    patient_name: str
    patient_dob: str
    patient_sex: str
    insured_name: str
    patient_address: str
    patient_city: str
    patient_state: str
    patient_zip: str
    diagnosis_codes: list
    service_lines: list
    billing_provider_name: str
    billing_provider_npi: str
    billing_provider_address: str
    total_charge: str
    amount_paid: str
    federal_tax_id: str
    accept_assignment: bool
    signature_on_file: bool
    errors: list


def _random_date(start_year: int = 2025, end_year: int = 2026) -> str:
    y = random.randint(start_year, end_year)
    if y == 2026:
        m = random.randint(1, 6)
        d = random.randint(1, 28) if m < 6 else random.randint(1, 30)
    else:
        m = random.randint(1, 12)
        d = random.randint(1, 28)
    return f"{m:02d}{d:02d}{y}"


def _random_dob() -> str:
    y = random.randint(1945, 2000)
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
    insurance_id = f"INS{random.randint(100_000_000, 999_999_999)}"
    patient_name = f"{random.choice(LAST_NAMES)} {random.choice(FIRST_NAMES)}"
    dob = _random_dob()
    sex = random.choice(["M", "F"])
    tax_id = str(random.randint(100_000_000, 999_999_999))
    city = random.choice(CITIES)
    state = random.choice(STATES)
    zipcode = str(random.randint(10000, 99999))
    address = f"{random.randint(100, 9999)} {random.choice(STREETS)}"
    billing_addr = f"{random.randint(1, 999)} MEDICAL PLAZA {city} {state} {zipcode}"

    if "missing_npi" in error_types:
        npi = ""
        errors.append({"field": "billing_provider_npi", "rule": "mandatory"})
    if "invalid_icd10" in error_types:
        codes[0] = "XXXXX"
        errors.append({"field": "diagnosis_codes", "rule": "icd10_lookup"})
    if "arithmetic_mismatch" in error_types:
        total += Decimal("10.00")
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
        patient_address=address,
        patient_city=city,
        patient_state=state,
        patient_zip=zipcode,
        diagnosis_codes=codes,
        service_lines=lines,
        billing_provider_name=billing_name,
        billing_provider_npi=npi,
        billing_provider_address=billing_addr,
        total_charge=str(total),
        amount_paid="0.00",
        federal_tax_id=tax_id,
        accept_assignment=True,
        signature_on_file=True,
        errors=errors,
    )


# ─── PDF RENDERER ─────────────────────────────────────────────────────────────

L = 5.0    # left edge (mm)
R = 210.9  # right edge (mm)
W = R - L  # content width (mm)


def _render_pdf(claim: ClaimData, out_path: Path) -> None:  # noqa: C901
    pdf = FPDF(format="letter")
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.add_page()

    # ── helpers ───────────────────────────────────────────────────────────────

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

    def lbl(x: float, y: float, text: str, w: float = 0, size: float = 5.5) -> None:
        eff_w = (w - 1) if w else (R - x - 1)
        line_h = size * 0.42
        for i, line in enumerate(_wrap(text, eff_w, size)):
            pdf.set_xy(x + 0.5, y + 0.5 + i * line_h)
            pdf.cell(eff_w, line_h, line, border=0)

    def val(x: float, y: float, text: str, w: float = 0, size: float = 9) -> None:
        pdf.set_xy(x + 1, y + 5)
        pdf.set_font("Helvetica", "", size)
        pdf.cell(w - 2 if w else 0, 5, str(text), border=0)

    def hln(x1: float, y: float, x2: float) -> None:
        pdf.line(x1, y, x2, y)

    def vln(x: float, y1: float, y2: float) -> None:
        pdf.line(x, y1, x, y2)

    def bx(x: float, y: float, bw: float, bh: float) -> None:
        pdf.rect(x, y, bw, bh)

    # ── header ────────────────────────────────────────────────────────────────
    bx(L, 5, W, 271)

    pdf.set_xy(L, 7)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(W, 8, "HEALTH INSURANCE CLAIM FORM", align="C", border=0)

    pdf.set_xy(R - 58, 5.5)
    pdf.set_font("Helvetica", "", 5)
    pdf.cell(55, 3, "APPROVED OMB-0938-0008", border=0)

    pdf.set_xy(L + 0.5, 5.5)
    pdf.set_font("Helvetica", "B", 4.5)
    pdf.cell(50, 3, "PLEASE DO NOT STAPLE IN THIS AREA", border=0)

    # ── row 1: insurance type | Box 1a ────────────────────────────────────────
    y = 14.0
    h = 10.0
    split = L + 128

    hln(L, y + h, R)
    vln(split, y, y + h)

    lbl(L, y, "1. MEDICARE  MEDICAID  CHAMPUS  CHAMPVA  GROUP HEALTH PLAN  FECA BLK LUNG  OTHER")
    val(L, y, "[X] OTHER", size=7)

    lbl(split, y, "1a. INSURED'S I.D. NUMBER  (FOR PROGRAM IN ITEM 1)", w=R - split)
    val(split, y, claim.insurance_id, w=R - split)

    # ── row 2: patient name | DOB/sex | insured name ──────────────────────────
    y += h
    h = 12.0
    c1 = L + 72
    c2 = L + 105

    hln(L, y + h, R)
    vln(c1, y, y + h)
    vln(c2, y, y + h)

    lbl(L, y, "2. PATIENT'S NAME (Last Name, First Name, Middle Initial)", w=c1 - L)
    val(L, y, claim.patient_name, w=c1 - L, size=8)

    dob = claim.patient_dob
    dob_fmt = f"{dob[0:2]} | {dob[2:4]} | {dob[4:8]}"
    lbl(c1, y, "3. PATIENT'S BIRTH DATE  MM  DD  YY", w=c2 - c1)
    val(c1, y, dob_fmt, w=c2 - c1, size=8)
    m_x = "[X]" if claim.patient_sex == "M" else "[ ]"
    f_x = "[X]" if claim.patient_sex == "F" else "[ ]"
    pdf.set_xy(c1 + 1, y + 8)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(c2 - c1 - 2, 4, f"SEX  {m_x} M  {f_x} F", border=0)

    lbl(c2, y, "4. INSURED'S NAME (Last Name, First Name, Middle Initial)", w=R - c2)
    val(c2, y, claim.insured_name, w=R - c2, size=8)

    # ── row 3: patient address | relationship | insured address ───────────────
    y += h
    h = 11.0

    hln(L, y + h, R)
    vln(c1, y, y + h)
    vln(c2, y, y + h)

    lbl(L, y, "5. PATIENT'S ADDRESS (No., Street)", w=c1 - L)
    val(L, y, claim.patient_address, w=c1 - L, size=8)

    lbl(c1, y, "6. PATIENT RELATIONSHIP TO INSURED", w=c2 - c1)
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_xy(c1 + 1, y + 5.5)
    pdf.cell(c2 - c1 - 2, 3, "[X] Self  [ ] Spouse", border=0)
    pdf.set_xy(c1 + 1, y + 8.3)
    pdf.cell(c2 - c1 - 2, 3, "[ ] Child  [ ] Other", border=0)

    lbl(c2, y, "7. INSURED'S ADDRESS (No., Street)", w=R - c2)
    val(c2, y, claim.patient_address, w=R - c2, size=8)

    # ── row 4: city/state | patient status | insured city/state ──────────────
    y += h
    h = 10.0

    hln(L, y + h, R)
    vln(c1, y, y + h)
    vln(c2, y, y + h)

    lbl(L, y, "CITY", w=45)
    val(L, y, claim.patient_city, w=43, size=8)
    lbl(L + 44, y, "STATE", w=28)
    val(L + 44, y, claim.patient_state, w=26, size=8)

    lbl(c1, y, "8. PATIENT STATUS", w=c2 - c1)
    pdf.set_font("Helvetica", "", 6)
    pdf.set_xy(c1 + 1, y + 4.8)
    pdf.cell(c2 - c1 - 2, 3, "[X] Employed  [ ] Full-Time", border=0)
    pdf.set_xy(c1 + 1, y + 7.3)
    pdf.cell(c2 - c1 - 2, 3, "[ ] Part-Time", border=0)

    lbl(c2, y, "CITY", w=45)
    val(c2, y, claim.patient_city, w=43, size=8)
    lbl(c2 + 44, y, "STATE", w=28)
    val(c2 + 44, y, claim.patient_state, w=26, size=8)

    # ── row 5: zip / telephone ────────────────────────────────────────────────
    y += h
    h = 9.0

    hln(L, y + h, R)
    vln(c1, y, y + h)
    vln(c2, y, y + h)

    lbl(L, y, "ZIP CODE", w=32)
    val(L, y, claim.patient_zip, w=30, size=8)
    lbl(L + 31, y, "TELEPHONE (Include Area Code)", w=41)

    lbl(c2, y, "ZIP CODE", w=32)
    val(c2, y, claim.patient_zip, w=30, size=8)
    lbl(c2 + 31, y, "TELEPHONE (INCLUDE AREA CODE)", w=41)

    # ── rows 9-11 (other insured / condition / insured policy) ────────────────
    y += h
    band_h = 40.0
    row_h = band_h / 5

    vln(c1, y, y + band_h)
    vln(c2, y, y + band_h)
    for i in range(1, 5):
        hln(L, y + i * row_h, c1)
        hln(c1, y + i * row_h, c2)
        hln(c2, y + i * row_h, R)
    hln(L, y + band_h, R)

    rows9 = [
        ("9. OTHER INSURED'S NAME", "10. IS PATIENT'S CONDITION RELATED TO:", "11. INSURED'S POLICY GROUP OR FECA NUMBER"),
        ("a. OTHER INSURED'S POLICY OR GROUP NUMBER", "a. EMPLOYMENT? (CURRENT OR PREVIOUS)", "a. INSURED'S DATE OF BIRTH  SEX"),
        ("b. OTHER INSURED'S DATE OF BIRTH  SEX", "b. AUTO ACCIDENT?  PLACE (State)", "b. EMPLOYER'S NAME OR SCHOOL NAME"),
        ("c. EMPLOYER'S NAME OR SCHOOL NAME", "c. OTHER ACCIDENT?", "c. INSURANCE PLAN NAME OR PROGRAM NAME"),
        ("d. INSURANCE PLAN NAME OR PROGRAM NAME", "10d. RESERVED FOR LOCAL USE", "d. IS THERE ANOTHER HEALTH BENEFIT PLAN?"),
    ]
    condition_vals = [None, "[ ] YES  [X] NO", "[ ] YES  [X] NO  PLACE: ___", "[ ] YES  [X] NO", "[X] YES  [ ] NO"]

    for i, (l9, l10, l11) in enumerate(rows9):
        ry = y + i * row_h
        lbl(L, ry, l9, w=c1 - L)
        lbl(c1, ry, l10, w=c2 - c1)
        lbl(c2, ry, l11, w=R - c2)
        if condition_vals[i]:
            pdf.set_xy(c1 + 1, ry + 4)
            pdf.set_font("Helvetica", "", 6)
            pdf.cell(c2 - c1 - 2, 3.5, condition_vals[i], border=0)

    # ── read-back notice + boxes 12 / 13 ─────────────────────────────────────
    y += band_h
    h = 14.0
    mid = L + 98

    hln(L, y + h, R)
    vln(mid, y, y + h)

    pdf.set_xy(L + 1, y + 1)
    pdf.set_font("Helvetica", "B", 5.5)
    pdf.cell(mid - L - 2, 3.5, "READ BACK OF FORM BEFORE COMPLETING & SIGNING THIS FORM.", border=0)

    lbl(L, y + 4, "12. PATIENT'S OR AUTHORIZED PERSON'S SIGNATURE", w=mid - L)
    pdf.set_xy(L + 1, y + 9)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(mid - L - 2, 4, "SIGNED ___________________  DATE __________", border=0)

    lbl(mid, y, "13. INSURED'S OR AUTHORIZED PERSON'S SIGNATURE", w=R - mid)
    pdf.set_xy(mid + 1, y + 7)
    pdf.set_font("Helvetica", "", 7)
    sig_val = "Signature on File" if claim.signature_on_file else ""
    pdf.cell(R - mid - 2, 4, f"SIGNED: {sig_val}", border=0)

    # ── row 14 / 15 / 16 ─────────────────────────────────────────────────────
    y += h
    h = 9.0
    r14a = L + 55
    r14b = L + 108

    hln(L, y + h, R)
    vln(r14a, y, y + h)
    vln(r14b, y, y + h)

    lbl(L, y, "14. DATE OF CURRENT: ILLNESS (First symptom) OR INJURY OR PREGNANCY(LMP)", w=r14a - L, size=4.5)
    lbl(r14a, y, "15. IF PATIENT HAD SAME/SIMILAR ILLNESS, GIVE FIRST DATE MM DD YY", w=r14b - r14a, size=4.5)
    lbl(r14b, y, "16. DATES PATIENT UNABLE TO WORK IN CURRENT OCCUPATION  From MM DD YY  To", w=R - r14b, size=4.5)

    # ── row 17 / 17a / 18 ────────────────────────────────────────────────────
    y += h
    h = 9.0
    r17a = L + 78
    r17b = L + 118

    hln(L, y + h, R)
    vln(r17a, y, y + h)
    vln(r17b, y, y + h)

    lbl(L, y, "17. NAME OF REFERRING PHYSICIAN OR OTHER SOURCE", w=r17a - L, size=4.5)
    lbl(r17a, y, "17a. I.D. NUMBER OF REFERRING PHYSICIAN", w=r17b - r17a, size=4.5)
    lbl(r17b, y, "18. HOSPITALIZATION DATES RELATED TO CURRENT SERVICES  From MM DD YY  To", w=R - r17b, size=4.5)

    # ── row 19 / 20 / 21 label ───────────────────────────────────────────────
    y += h
    h = 8.0
    r19a = L + 78
    r19b = L + 118

    hln(L, y + h, R)
    vln(r19a, y, y + h)
    vln(r19b, y, y + h)

    lbl(L, y, "19. RESERVED FOR LOCAL USE", w=r19a - L)
    lbl(r19a, y, "20. OUTSIDE LAB?  [ ] YES  [X] NO   $ CHARGES", w=r19b - r19a)
    lbl(r19b, y, "21. DIAGNOSIS OR NATURE OF ILLNESS OR INJURY. (RELATE ITEMS 1,2,3 OR 4 TO ITEM 24E BY LINE)", w=R - r19b, size=4.5)

    # ── diagnosis codes 1-4 | boxes 22-23 ────────────────────────────────────
    y += h
    h = 16.0
    diag_split = L + 118
    diag_mid = L + 62   # vertical between code columns 1,2 and 3,4
    diag_row2 = y + h / 2

    vln(diag_split, y, y + h)
    hln(L, diag_row2, diag_split)
    hln(diag_split, y + h / 2, R)
    hln(L, y + h, R)
    vln(diag_mid, y, y + h)

    codes = claim.diagnosis_codes

    def diag_slot(dx: float, dy: float, num: str, code: str) -> None:
        pdf.set_xy(dx + 1, dy + 2)
        pdf.set_font("Helvetica", "B", 7)
        pdf.cell(6, 4, f"{num}.", border=0)
        pdf.set_xy(dx + 7, dy + 2)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(40, 6, code, border=0)

    diag_slot(L, y, "1", codes[0] if len(codes) > 0 else "")
    diag_slot(diag_mid, y, "3", codes[2] if len(codes) > 2 else "")
    diag_slot(L, diag_row2, "2", codes[1] if len(codes) > 1 else "")
    diag_slot(diag_mid, diag_row2, "4", codes[3] if len(codes) > 3 else "")

    lbl(diag_split, y, "22. MEDICAID RESUBMISSION  CODE  ORIGINAL REF. NO.", w=R - diag_split)
    lbl(diag_split, diag_row2, "23. PRIOR AUTHORIZATION NUMBER", w=R - diag_split)

    # ── box 24 header ─────────────────────────────────────────────────────────
    y += h
    hdr_h = 11.0

    # Column x-positions and widths
    c24 = {
        "dos_from": (L, 15),
        "dos_to":   (L + 15, 14),
        "pos":      (L + 29, 10),
        "typ":      (L + 39, 9),
        "cpt":      (L + 48, 25),
        "mod":      (L + 73, 17),
        "diag":     (L + 90, 24),
        "chg":      (L + 114, 25),
        "days":     (L + 139, 14),
        "epsdt":    (L + 153, 13),
        "emg":      (L + 166, 10),
        "cob":      (L + 176, 10),
        "rsv":      (L + 186, R - L - 186),
    }

    bx(L, y, W, hdr_h)
    for key, (cx, cw) in c24.items():
        if cx > L:
            vln(cx, y, y + hdr_h)

    def chdr(cx: float, cw: float, text: str, dy: float = 0) -> None:
        eff_w = cw - 0.6
        size = 4.5
        line_h = size * 0.42
        for i, line in enumerate(_wrap(text, eff_w, size)):
            pdf.set_xy(cx + 0.3, y + 0.3 + dy + i * line_h)
            pdf.cell(eff_w, line_h, line, border=0)

    chdr(L, 29, "24. A.  DATE(S) OF SERVICE")
    chdr(L, 14, "From  MM  DD  YY", dy=3.5)
    chdr(L + 15, 14, "To  MM  DD  YY", dy=3.5)
    chdr(L + 29, 10, "B. PLACE OF SERVICE")
    chdr(L + 39, 9, "C. TYPE OF SERVICE")
    chdr(L + 48, 42, "D. PROCEDURES, SERVICES, OR SUPPLIES (Explain Unusual Circumstances)")
    chdr(L + 48, 25, "CPT/HCPCS", dy=3.5)
    chdr(L + 73, 17, "MODIFIER", dy=3.5)
    chdr(L + 90, 24, "E. DIAGNOSIS CODE")
    chdr(L + 114, 25, "F. $ CHARGES")
    chdr(L + 139, 14, "G. DAYS OR UNITS")
    chdr(L + 153, 13, "H. EPSDT Family Plan")
    chdr(L + 166, 10, "I. EMG")
    chdr(L + 176, 10, "J. COB")
    chdr(L + 186, R - L - 186, "K. RESERVED FOR LOCAL USE")

    # Sub-divider between CPT and MODIFIER header
    hln(L, y + 3.8, L + 29)
    hln(L + 48, y + 3.8, L + 90)

    # ── service line rows ─────────────────────────────────────────────────────
    y += hdr_h
    svc_h = 8.5

    for i in range(6):
        ry = y + i * svc_h
        bx(L, ry, W, svc_h)
        for key, (cx, cw) in c24.items():
            if cx > L:
                vln(cx, ry, ry + svc_h)

        # Row number at bottom of cell so it doesn't merge with date in text extraction
        pdf.set_xy(L + 0.5, ry + 6.5)
        pdf.set_font("Helvetica", "", 5)
        pdf.cell(4, 2.5, str(i + 1), border=0)

        if i < len(claim.service_lines):
            svc = claim.service_lines[i]
            dos = svc["date_of_service"]
            # MM/DD/YY — compact enough for the 15mm column
            dos_fmt = f"{dos[0:2]}/{dos[2:4]}/{dos[6:8]}"

            def sv(cx: float, text: str, sz: float = 8) -> None:
                pdf.set_xy(cx + 0.5, ry + 2)
                pdf.set_font("Helvetica", "", sz)
                pdf.cell(20, 5, str(text), border=0)

            sv(L, dos_fmt, 7)
            sv(L + 15, dos_fmt, 7)
            sv(L + 29, svc["place_of_service"])
            sv(L + 48, svc["cpt_code"])
            sv(L + 90, svc["diagnosis_pointer"])
            sv(L + 114, f"${svc['charges']}")
            sv(L + 139, str(svc["units"]))

    # ── boxes 25-30 (financial row) ───────────────────────────────────────────
    y += 6 * svc_h
    fin_h = 11.0

    fin_cols = [
        (L,       47, "25. FEDERAL TAX I.D. NUMBER    SSN  EIN"),
        (L + 47,  28, "26. PATIENT'S ACCOUNT NO."),
        (L + 75,  30, "27. ACCEPT ASSIGNMENT?  (For govt. claims, see back)"),
        (L + 105, 30, "28. TOTAL CHARGE"),
        (L + 135, 30, "29. AMOUNT PAID"),
        (L + 165, R - L - 165, "30. BALANCE DUE"),
    ]

    hln(L, y + fin_h, R)
    for fx, fw, flabel in fin_cols:
        vln(fx, y, y + fin_h)
        lbl(fx, y, flabel, w=fw)
    vln(R, y, y + fin_h)

    def fv(fx: float, text: str, sz: float = 8) -> None:
        pdf.set_xy(fx + 1, y + 5)
        pdf.set_font("Helvetica", "", sz)
        pdf.cell(40, 5, str(text), border=0)

    fv(L, f"{claim.federal_tax_id}   [ ] SSN  [X] EIN")
    yes_x = "[X]" if claim.accept_assignment else "[ ]"
    no_x = "[ ]" if claim.accept_assignment else "[X]"
    fv(L + 75, f"{yes_x} YES  {no_x} NO")
    fv(L + 105, f"$ {claim.total_charge}")
    fv(L + 135, f"$ {claim.amount_paid}")
    fv(L + 165, "$ 0.00")

    # ── boxes 31 / 32 / 33 (signature / facility / billing) ──────────────────
    y += fin_h
    sig_h = 18.0
    col31 = 58.0
    col32 = 80.0
    col33 = W - col31 - col32

    bx(L, y, col31, sig_h)
    bx(L + col31, y, col32, sig_h)
    bx(L + col31 + col32, y, col33, sig_h)

    lbl(L, y, "31. SIGNATURE OF PHYSICIAN OR SUPPLIER INCLUDING DEGREES OR CREDENTIALS", w=col31)
    pdf.set_xy(L + 1, y + 6)
    pdf.set_font("Helvetica", "", 7)
    sig_text = "Signature on File" if claim.signature_on_file else "______________________"
    pdf.cell(col31 - 2, 4, f"SIGNED: {sig_text}", border=0)
    pdf.set_xy(L + 1, y + 12)
    pdf.cell(col31 - 2, 4, "DATE: _______________", border=0)

    lbl(L + col31, y, "32. NAME AND ADDRESS OF FACILITY WHERE SERVICES WERE RENDERED (If other than home or office)", w=col32)

    lbl(L + col31 + col32, y, "33. PHYSICIAN'S, SUPPLIER'S BILLING NAME, ADDRESS, ZIP CODE & PHONE #", w=col33)
    pdf.set_xy(L + col31 + col32 + 1, y + 5)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.cell(col33 - 2, 4, claim.billing_provider_name, border=0)
    pdf.set_xy(L + col31 + col32 + 1, y + 10)
    pdf.cell(col33 - 2, 4, claim.billing_provider_address[:40], border=0)
    pdf.set_xy(L + col31 + col32 + 1, y + 15)
    pdf.cell(col33 - 2, 4, f"PIN# {claim.billing_provider_npi}   GRP# ___", border=0)

    # footer
    y += sig_h
    pdf.set_xy(L, y + 1)
    pdf.set_font("Helvetica", "", 5)
    pdf.cell(
        W, 3,
        "(APPROVED BY AMA COUNCIL ON MEDICAL SERVICE 8/88)     PLEASE PRINT OR TYPE"
        "     FORM HCFA-1500 (12-90), FORM RRB-1500, FORM OWCP-1500",
        align="C", border=0,
    )

    pdf.output(str(out_path))


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic/health"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for i in range(args.count):
        error_types = ERROR_POOL[i % len(ERROR_POOL)]
        claim = _make_claim(error_types)
        pkg_dir = args.out / f"package_{i:03d}"
        pkg_dir.mkdir(exist_ok=True)
        _render_pdf(claim, pkg_dir / "claim.pdf")
        gt_fields = {k: v for k, v in asdict(claim).items() if k != "errors"}
        gt = {"fields": gt_fields, "errors": claim.errors}
        (pkg_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

    print(f"Generated {args.count} packages in {args.out}")


if __name__ == "__main__":
    main()
