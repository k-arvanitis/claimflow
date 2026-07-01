"""Download ICD-10-CM and a public CPT substitute into data/lookups/.

ICD-10-CM: CMS publishes annual code tables as CSV (public domain).
CPT: AMA codes are proprietary; we use HCPCS Level II (public) as a
     stand-in for the portfolio demo. Real deployments would use AMA data.
"""
import csv
import io
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "lookups"
OUT.mkdir(parents=True, exist_ok=True)

ICD10_URL = "https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order.zip"
# HCPCS Level II (public) as CPT substitute for demo
HCPCS_URL = "https://www.cms.gov/files/zip/2025-alpha-numeric-hcpcs-file.zip"


def _download_icd10() -> None:
    print("Downloading ICD-10-CM...")
    with urllib.request.urlopen(ICD10_URL) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.endswith("icd10cm_codes_2026.txt") or "codes" in n.lower() and n.endswith(".txt")]
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
    print(f"  → {out} ({sum(1 for _ in open(out))-1} codes)")


def _download_cpt() -> None:
    print("Downloading HCPCS Level II (CPT stand-in)...")
    with urllib.request.urlopen(HCPCS_URL) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".xlsx") or n.lower().endswith(".txt")]
        if not names:
            raise RuntimeError(f"Unexpected HCPCS zip contents: {z.namelist()}")
        # Write as-is, parse first column as code
        raw = z.read(names[0]).decode("latin-1", errors="replace")
    out = OUT / "cpt.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "description"])
        for line in raw.splitlines():
            if line.strip():
                parts = line.split()
                if parts and len(parts[0]) <= 7:
                    w.writerow([parts[0], " ".join(parts[1:])])
    print(f"  → {out}")


if __name__ == "__main__":
    _download_icd10()
    _download_cpt()
    print("Done.")
