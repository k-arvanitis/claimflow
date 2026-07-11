"""Download ICD-10-CM and a public CPT substitute into data/lookups/.

ICD-10-CM: CMS publishes annual code tables as CSV (public domain).
CPT: AMA codes are proprietary; real HCPCS Level II data can't stand in for it either
     (Level II structurally excludes CPT-4), so this generates a synthetic numeric-range
     placeholder instead of fetching real HCPCS data — pretending to fetch "real" data
     for a validator that can never check real CPT codes would be misleading. Real HCPCS
     Level II data (for genuinely HCPCS-coded validation, not as a CPT stand-in) lives in
     eval/real_public/scripts/download_real_public.py's download_real_hcpcs() instead.
"""
import csv
import io
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "lookups"
OUT.mkdir(parents=True, exist_ok=True)

ICD10_URL = "https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order.zip"


def _download_icd10() -> None:
    print("Downloading ICD-10-CM...")
    with urllib.request.urlopen(ICD10_URL) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [
            n for n in z.namelist()
            if n.endswith("icd10cm_codes_2026.txt") or ("codes" in n.lower() and n.endswith(".txt"))
        ]
        if not names:
            raise RuntimeError(f"Unexpected zip contents: {z.namelist()}")
        raw = z.read(names[0]).decode("utf-8", errors="replace")
    out = OUT / "icd10.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "description"])
        for line in raw.splitlines():
            if line.strip():
                code, _, desc = line.partition(" ")
                w.writerow([code.strip(), desc.strip()])
    with open(out) as f:
        count = sum(1 for _ in f) - 1
    print(f"  → {out} ({count} codes)")


def _generate_cpt_fallback(out: Path) -> None:
    """Generate CPT codes from standard numeric ranges (used when CMS URL is unavailable)."""
    ranges = [
        (99201, 99499, "Evaluation and Management"),
        (70010, 79999, "Radiology"),
        (80047, 89398, "Pathology/Laboratory"),
        (90281, 99607, "Medicine"),
        (10021, 69990, "Surgery"),
    ]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "description"])
        for start, end, category in ranges:
            for code in range(start, end + 1):
                w.writerow([str(code), category])
    with open(out) as f:
        count = sum(1 for _ in f) - 1
    print(f"  → {out} ({count} codes, generated from ranges)")


def _download_cpt() -> None:
    print("Generating CPT stand-in (synthetic numeric ranges)...")
    _generate_cpt_fallback(OUT / "cpt.csv")


if __name__ == "__main__":
    _download_icd10()
    _download_cpt()
    print("Done.")
