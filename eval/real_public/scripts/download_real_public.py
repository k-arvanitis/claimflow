"""Download public datasets for ClaimFlow's domain-specific real/public eval layer
(health/property/loan). Horizontal, domain-agnostic benchmarks (FUNSD OCR/layout,
RVL-CDIP classification) live in doc-intel's own eval instead — they test doc-intel's
core OCR/classification mechanisms independent of any ClaimFlow business domain.

Raw downloads land under $CLAIMFLOW_EVAL_DATA_DIR (default: data/real_public) —
never committed to git. Each downloaded artifact gets a manifest entry recorded
in eval/real_public/manifest.json (source URL, sha256, accessed_at, license/PII notes).

Usage:
    uv run python eval/real_public/scripts/download_real_public.py --dataset synpuf
"""

import argparse
import csv
import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

_DATA_DIR = Path(os.environ.get("CLAIMFLOW_EVAL_DATA_DIR", "data/real_public"))
_MANIFEST_PATH = Path(__file__).parent.parent / "manifest.json"
_REPO_ROOT = Path(__file__).parent.parent.parent.parent

CMS1500_TEMPLATE_URL = (
    "https://www.cms.gov/medicare/cms-forms/cms-forms/downloads/cms1500.pdf"
)
SYNPUF_OUTPATIENT_URL = (
    "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/"
    "synpufs/downloads/de1_0_2008_to_2010_outpatient_claims_sample_1.zip"
)
NPI_REGISTRY_API = "https://npiregistry.cms.hhs.gov/api/"
FEMA_IHP_API = (
    "https://www.fema.gov/api/open/v2/IndividualsAndHouseholdsProgramValidRegistrations"
)

# Public sample Xactimate-style estimate PDFs (third-party contractor/estimator sites —
# blog-hosted, so these can 404 or move; treat as best-effort, verify before relying on them).
XACTIMATE_SAMPLE_PDFS = {
    "empireestimators_sample1": "https://www.empireestimators.com/wp-content/uploads/2015/05/Sample-Estimate-I.pdf",
    "hhhroofing_example": "https://hhhroofing.com/wp-content/uploads/2022/01/Xactimate-Estimate-Example.pdf",
    "workflowsolutions_roof_example3": "https://workflowsolutionsllc.com/wp-content/uploads/2021/05/Roof-Example-3.pdf",
}

SBA_7A_FY2020_PRESENT_URL = (
    "https://data.sba.gov/en/dataset/0ff8e8e9-b967-4f4e-987c-6ac78c575087/resource/"
    "d67d3ccb-2002-4134-a288-481b51cd3479/download/foia-7a-fy2020-present-asof-260331.csv"
)
SBA_PPP_OVER_150K_URL = (
    "https://data.sba.gov/dataset/8aa276e2-6cab-4f86-aca4-a7dde42adf24/resource/"
    "c1275a03-c25c-488a-bd95-403c4b2fa036/download/public_150k_plus_240930.csv"
)
SBA_FORM_1919_PDF = "https://www.sba.gov/sites/default/files/2025-03/2025.02.27%20Form%201919%20-%20Updates%20%28FINAL%29_03-12-2025%20%281%29.pdf"
SBA_FORM_413_PDF = "https://www.sba.gov/sites/default/files/2025-02/SBAForm413.pdf"
SBA_FORM_2202_PDF = "https://www.sba.gov/sites/default/files/2020-07/2202%20Schedule%20of%20Liabilities-508.pdf"

CMS_SAMPLE_EOB_PDF = (
    "https://www.cms.gov/files/document/11819-sample-explanation-benefits-508.pdf"
)

# Public sample declarations pages. Maryland Insurance Administration's PDF returns
# HTTP 403 to non-browser clients (bot-blocking WAF) — Florida CFO's is reachable and
# used as the fixture; Maryland is documented as unreachable in failures.md, not faked.
DECLARATIONS_PAGE_PDFS = {
    "florida_cfo_sample_declarations": (
        "https://www.myfloridacfo.com/docs-sf/consumer-services-libraries/consumerservices-"
        "documents/understanding-coverage/sample-declarations-page.pdf?sfvrsn=7d9437e7_3"
    ),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> list[dict]:
    if _MANIFEST_PATH.exists():
        return json.loads(_MANIFEST_PATH.read_text())
    return []


def _save_manifest(entries: list[dict]) -> None:
    _MANIFEST_PATH.write_text(json.dumps(entries, indent=2))


def _upsert_manifest_entry(entry: dict) -> None:
    entries = _load_manifest()
    entries = [e for e in entries if e["doc_id"] != entry["doc_id"]]
    entries.append(entry)
    _save_manifest(entries)


def _download_file(url: str, dest: Path) -> None:
    req = Request(
        url, headers={"User-Agent": "Mozilla/5.0 (ClaimFlow eval data fetch)"}
    )
    with urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())


def register_health_lookups() -> None:
    """Register the existing ICD-10-CM lookup (already fetched from the official CMS
    URL by scripts/download_lookups.py) into the real/public manifest with provenance.

    NOTE: production's data/lookups/cpt.csv is NOT real HCPCS data — it's a synthetic
    numeric-range placeholder used deliberately, because real HCPCS Level II legitimately
    excludes CPT-4 (AMA-licensed) codes and so cannot validate the CPT-style E&M codes the
    synthetic eval generates. See download_real_hcpcs() below for the real HCPCS fetch,
    kept separate and used only against HCPCS-native data (e.g. SynPUF's HCPCS_CD_* fields).
    """
    path = _REPO_ROOT / "data" / "lookups" / "icd10.csv"
    if not path.exists():
        print(
            "  icd10.csv not found — run `uv run python scripts/download_lookups.py` first"
        )
        return
    _upsert_manifest_entry(
        {
            "doc_id": "cdc_cms_icd10cm_codes",
            "dataset": "cms_official_code_lists",
            "domain": "health",
            "document_type": "code_lookup_table",
            "source_url": "https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order.zip",
            "local_path": str(path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": _sha256(path),
            "license_public_use_notes": "ICD-10-CM codes published by CMS; public domain U.S. government work.",
            "pii_status": "public_non_pii",
            "split": "reference",
            "gold_path": None,
        }
    )
    print(f"  registered ICD-10-CM: {path} ({_sha256(path)[:12]}...)")


def download_real_hcpcs() -> Path:
    """Real HCPCS Level II codes (alphanumeric, non-CPT) — kept separate from production's
    synthetic data/lookups/cpt.csv. Used to validate SynPUF's genuinely-HCPCS-coded fields,
    not as a CPT stand-in (HCPCS Level II structurally excludes CPT-4)."""
    out_dir = _DATA_DIR / "health"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "hcpcs_real.csv"
    hcpcs_url = "https://www.cms.gov/files/zip/april-2026-alpha-numeric-hcpcs-file.zip"

    if not out_path.exists():
        import openpyxl

        print(f"Downloading {hcpcs_url} ...")
        req = Request(
            hcpcs_url, headers={"User-Agent": "Mozilla/5.0 (ClaimFlow eval data fetch)"}
        )
        with urlopen(req, timeout=60) as resp:
            zip_bytes = resp.read()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Read the .xlsx, not the fixed-width .txt — the .txt's column boundaries
            # are undocumented/easy to get wrong (an earlier attempt concatenated the
            # code field with the next column); the .xlsx has clean, named columns.
            names = [n for n in zf.namelist() if n.upper().endswith("ANWEB.XLSX")]
            if not names:
                raise RuntimeError(f"Expected an ANWEB.xlsx file, got: {zf.namelist()}")
            xlsx_bytes = zf.read(names[0])
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
        ws = wb.active
        with open(out_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["code", "description"])
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    continue  # header row
                code = str(row[0]).strip() if row[0] else ""
                desc = str(row[3]).strip() if len(row) > 3 and row[3] else ""
                if code:
                    w.writerow([code, desc])

    sha256 = _sha256(out_path)
    with open(out_path) as f:
        n_codes = sum(1 for _ in f) - 1
    _upsert_manifest_entry(
        {
            "doc_id": "cms_hcpcs_level2_real",
            "dataset": "cms_official_code_lists",
            "domain": "health",
            "document_type": "code_lookup_table",
            "source_url": hcpcs_url,
            "local_path": str(out_path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256,
            "license_public_use_notes": (
                "HCPCS Level II codes published by CMS; public domain U.S. government work. "
                "NOT a CPT substitute — HCPCS Level II structurally excludes CPT-4 (AMA-licensed) codes."
            ),
            "pii_status": "public_non_pii",
            "split": "reference",
            "gold_path": None,
        }
    )
    print(
        f"  registered real HCPCS Level II: {out_path} ({n_codes} codes, sha256 {sha256[:12]}...)"
    )
    return out_path


def download_cms1500_template() -> Path:
    """Official blank CMS-1500/NUCC form template — layout reference, not a completed claim."""
    out_dir = _DATA_DIR / "health"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "cms1500_template.pdf"
    if not pdf_path.exists():
        print(f"Downloading {CMS1500_TEMPLATE_URL} ...")
        _download_file(CMS1500_TEMPLATE_URL, pdf_path)
    sha256 = _sha256(pdf_path)
    _upsert_manifest_entry(
        {
            "doc_id": "cms1500_official_template",
            "dataset": "cms1500_template",
            "domain": "health",
            "document_type": "cms1500",
            "source_url": CMS1500_TEMPLATE_URL,
            "local_path": str(pdf_path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256,
            "license_public_use_notes": "Official blank CMS-1500 form template published by CMS; public domain U.S. government work.",
            "pii_status": "public_non_pii",
            "split": "reference",
            "gold_path": None,
        }
    )
    print(f"CMS-1500 template saved: {pdf_path} ({sha256[:12]}...)")
    return pdf_path


def download_synpuf_sample() -> Path:
    """CMS DE-SynPUF outpatient claims sample — fully synthetic Medicare-like claims, no PHI."""
    out_dir = _DATA_DIR / "health"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / "synpuf_outpatient_sample1.zip"
    if not zip_path.exists():
        print(f"Downloading {SYNPUF_OUTPATIENT_URL} ...")
        _download_file(SYNPUF_OUTPATIENT_URL, zip_path)
    sha256 = _sha256(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir / "synpuf")
    _upsert_manifest_entry(
        {
            "doc_id": "cms_synpuf_outpatient_sample1",
            "dataset": "cms_synpuf",
            "domain": "health",
            "document_type": "claims_table",
            "source_url": SYNPUF_OUTPATIENT_URL,
            "local_path": str(zip_path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256,
            "license_public_use_notes": (
                "CMS DE-SynPUF: fully synthetic Medicare claims data, engineered by CMS specifically "
                "to contain no real beneficiary information. Public use file."
            ),
            "pii_status": "synthetic_public",
            "split": "reference",
            "gold_path": None,
        }
    )
    print(f"SynPUF outpatient sample saved: {zip_path} ({sha256[:12]}...)")
    return zip_path


def download_nppes_sample() -> Path:
    """A small, deterministic sample of real, currently-active NPPES organizational NPI
    records via the official NPI Registry search API (no PHI — public provider directory)."""
    out_dir = _DATA_DIR / "health"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "nppes_sample.json"

    queries = [
        "organization_name=hospital*&state=CA",
        "organization_name=clinic*&state=TX",
        "organization_name=medical*&state=NY",
    ]
    all_results = []
    for q in queries:
        url = f"{NPI_REGISTRY_API}?version=2.1&limit=10&{q}"
        req = Request(
            url, headers={"User-Agent": "Mozilla/5.0 (ClaimFlow eval data fetch)"}
        )
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        all_results.extend(data.get("results", []))

    out_path.write_text(json.dumps(all_results, indent=2))
    sha256 = _sha256(out_path)
    _upsert_manifest_entry(
        {
            "doc_id": "nppes_sample_orgs",
            "dataset": "nppes",
            "domain": "health",
            "document_type": "provider_registry",
            "source_url": NPI_REGISTRY_API,
            "local_path": str(out_path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256,
            "license_public_use_notes": (
                "NPPES NPI Registry is a public CMS provider directory; providers consent to public "
                "disclosure of this information by registering for an NPI."
            ),
            "pii_status": "public_non_pii",
            "split": "reference",
            "gold_path": None,
        }
    )
    print(
        f"NPPES sample saved: {out_path} ({len(all_results)} records, sha256 {sha256[:12]}...)"
    )
    return out_path


def download_xactimate_samples() -> Path:
    """Public sample Xactimate-style property estimate PDFs from contractor/estimator sites.
    Best-effort: these are third-party blog-hosted files, not a stable dataset host."""
    out_dir = _DATA_DIR / "property" / "xactimate_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for doc_id, url in XACTIMATE_SAMPLE_PDFS.items():
        pdf_path = out_dir / f"{doc_id}.pdf"
        try:
            if not pdf_path.exists():
                print(f"Downloading {url} ...")
                _download_file(url, pdf_path)
            sha256 = _sha256(pdf_path)
            _upsert_manifest_entry(
                {
                    "doc_id": doc_id,
                    "dataset": "public_xactimate",
                    "domain": "property",
                    "document_type": "xactimate",
                    "source_url": url,
                    "local_path": str(pdf_path),
                    "accessed_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": sha256,
                    "license_public_use_notes": (
                        "Publicly posted sample estimate PDF from a contractor/estimator marketing "
                        "site, used for layout/extraction testing. Not a licensed Xactimate dataset."
                    ),
                    "pii_status": "unknown_check_manually",
                    "split": "test",
                    "gold_path": None,
                }
            )
            saved.append(pdf_path)
            print(f"  saved {doc_id}: {pdf_path} ({sha256[:12]}...)")
        except Exception as e:
            print(f"  FAILED {doc_id} ({url}): {e}")
    return out_dir


def download_fema_ihp_sample() -> Path:
    """Small subset of FEMA's public, PII-scrubbed disaster registration records."""
    out_dir = _DATA_DIR / "property"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "fema_ihp_sample.json"

    url = f"{FEMA_IHP_API}?$top=50"
    req = Request(
        url, headers={"User-Agent": "Mozilla/5.0 (ClaimFlow eval data fetch)"}
    )
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    records = data.get("IndividualsAndHouseholdsProgramValidRegistrations", [])
    out_path.write_text(json.dumps(records, indent=2))
    sha256 = _sha256(out_path)

    _upsert_manifest_entry(
        {
            "doc_id": "fema_ihp_valid_registrations_sample",
            "dataset": "fema_ihp",
            "domain": "property",
            "document_type": "disaster_loss_table",
            "source_url": FEMA_IHP_API,
            "local_path": str(out_path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256,
            "license_public_use_notes": (
                "FEMA OpenFEMA public dataset — Individuals and Households Program Valid "
                "Registrations. FEMA states this dataset has PII removed prior to publication."
            ),
            "pii_status": "public_non_pii",
            "split": "reference",
            "gold_path": None,
        }
    )
    print(
        f"FEMA IHP sample saved: {out_path} ({len(records)} records, sha256 {sha256[:12]}...)"
    )
    return out_path


def _stream_csv_rows(url: str, dest: Path, min_rows: int) -> None:
    """Stream a URL and stop once at least min_rows lines are buffered, instead of
    downloading a whole multi-hundred-MB file for a small deterministic sample.
    Trims the final (possibly truncated) line before writing."""
    req = Request(
        url, headers={"User-Agent": "Mozilla/5.0 (ClaimFlow eval data fetch)"}
    )
    buf = b""
    with urlopen(req, timeout=30) as resp:
        while buf.count(b"\n") < min_rows:
            chunk = resp.read(65536)
            if not chunk:
                break
            buf += chunk
    lines = buf.split(b"\n")
    dest.write_bytes(b"\n".join(lines[:-1]))


def download_sba_loan_samples() -> Path:
    """SBA 7(a) FOIA loan-level data (full FY2020-present file — SBA's server ignores
    HTTP Range requests, so this pulls the complete file) and a small streamed PPP sample."""
    out_dir = _DATA_DIR / "loan"
    out_dir.mkdir(parents=True, exist_ok=True)

    sba7a_path = out_dir / "sba_7a_fy2020_present_full.csv"
    if not sba7a_path.exists():
        print(
            f"Downloading {SBA_7A_FY2020_PRESENT_URL} (full file, ~150MB — server ignores Range) ..."
        )
        _download_file(SBA_7A_FY2020_PRESENT_URL, sba7a_path)
    sha_7a = _sha256(sba7a_path)
    with open(sba7a_path, "rb") as f:
        n_rows = sum(1 for _ in f) - 1
    _upsert_manifest_entry(
        {
            "doc_id": "sba_7a_fy2020_present",
            "dataset": "sba_7a_504_foia",
            "domain": "loan",
            "document_type": "loan_table",
            "source_url": SBA_7A_FY2020_PRESENT_URL,
            "local_path": str(sba7a_path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha_7a,
            "license_public_use_notes": "SBA 7(a) loan-level FOIA disclosure data; public record under FOIA.",
            "pii_status": "public_non_pii",
            "split": "reference",
            "gold_path": None,
        }
    )
    print(f"  SBA 7(a): {sba7a_path} ({n_rows} loan records, sha256 {sha_7a[:12]}...)")

    ppp_path = out_dir / "sba_ppp_over150k_sample.csv"
    if not ppp_path.exists():
        print(
            f"Streaming a small sample from {SBA_PPP_OVER_150K_URL} (full file is ~450MB) ..."
        )
        _stream_csv_rows(SBA_PPP_OVER_150K_URL, ppp_path, min_rows=250)
    sha_ppp = _sha256(ppp_path)
    with open(ppp_path, "rb") as f:
        n_ppp_rows = sum(1 for _ in f) - 1
    _upsert_manifest_entry(
        {
            "doc_id": "sba_ppp_over150k_sample",
            "dataset": "sba_ppp_foia",
            "domain": "loan",
            "document_type": "loan_table",
            "source_url": SBA_PPP_OVER_150K_URL,
            "local_path": str(ppp_path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha_ppp,
            "license_public_use_notes": (
                "SBA PPP loan-level FOIA disclosure data (loans over $150k); public record under FOIA. "
                "Only the first ~250 rows of the full ~450MB file were retained for this portfolio sample."
            ),
            "pii_status": "public_non_pii",
            "split": "reference",
            "gold_path": None,
        }
    )
    print(
        f"  SBA PPP sample: {ppp_path} ({n_ppp_rows} loan records, sha256 {sha_ppp[:12]}...)"
    )
    return out_dir


def download_sba_forms() -> Path:
    """Official blank SBA loan application forms — layout reference, not completed applications."""
    out_dir = _DATA_DIR / "loan"
    out_dir.mkdir(parents=True, exist_ok=True)
    for doc_id, url, filename in [
        ("sba_form_1919", SBA_FORM_1919_PDF, "sba_form_1919.pdf"),
        ("sba_form_413", SBA_FORM_413_PDF, "sba_form_413.pdf"),
        ("sba_form_2202", SBA_FORM_2202_PDF, "sba_form_2202.pdf"),
    ]:
        pdf_path = out_dir / filename
        if not pdf_path.exists():
            print(f"Downloading {url} ...")
            _download_file(url, pdf_path)
        sha256 = _sha256(pdf_path)
        _upsert_manifest_entry(
            {
                "doc_id": doc_id,
                "dataset": "sba_official_forms",
                "domain": "loan",
                "document_type": "sba_form",
                "source_url": url,
                "local_path": str(pdf_path),
                "accessed_at": datetime.now(timezone.utc).isoformat(),
                "sha256": sha256,
                "license_public_use_notes": "Official blank SBA form; public domain U.S. government work.",
                "pii_status": "public_non_pii",
                "split": "reference",
                "gold_path": None,
            }
        )
        print(f"  {doc_id}: {pdf_path} ({sha256[:12]}...)")
    return out_dir


def download_eob_sample() -> Path:
    """Official CMS sample Explanation of Benefits / Medicare Summary Notice PDF."""
    out_dir = _DATA_DIR / "health"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "cms_sample_eob.pdf"
    if not pdf_path.exists():
        print(f"Downloading {CMS_SAMPLE_EOB_PDF} ...")
        _download_file(CMS_SAMPLE_EOB_PDF, pdf_path)
    sha256 = _sha256(pdf_path)
    _upsert_manifest_entry(
        {
            "doc_id": "cms_sample_eob",
            "dataset": "cms_sample_eob",
            "domain": "health",
            "document_type": "eob",
            "source_url": CMS_SAMPLE_EOB_PDF,
            "local_path": str(pdf_path),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256,
            "license_public_use_notes": "Official CMS sample EOB/MSN; public domain U.S. government work.",
            "pii_status": "public_non_pii",
            "split": "test",
            "gold_path": None,
        }
    )
    print(f"  cms_sample_eob: {pdf_path} ({sha256[:12]}...)")
    return pdf_path


def download_declarations_page_samples() -> Path:
    """Public sample homeowners/property insurance declarations pages."""
    out_dir = _DATA_DIR / "property"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for doc_id, url in DECLARATIONS_PAGE_PDFS.items():
        pdf_path = out_dir / f"{doc_id}.pdf"
        try:
            if not pdf_path.exists():
                print(f"Downloading {url} ...")
                _download_file(url, pdf_path)
            sha256 = _sha256(pdf_path)
            _upsert_manifest_entry(
                {
                    "doc_id": doc_id,
                    "dataset": "public_declarations_page",
                    "domain": "property",
                    "document_type": "declarations_page",
                    "source_url": url,
                    "local_path": str(pdf_path),
                    "accessed_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": sha256,
                    "license_public_use_notes": (
                        "Public state-agency consumer-education sample declarations page, used for "
                        "layout/extraction testing. Not a real policyholder's declarations page."
                    ),
                    "pii_status": "public_non_pii",
                    "split": "test",
                    "gold_path": None,
                }
            )
            saved.append(pdf_path)
            print(f"  saved {doc_id}: {pdf_path} ({sha256[:12]}...)")
        except Exception as e:
            print(f"  FAILED {doc_id} ({url}): {e}")
    return out_dir


DATASETS = {
    "health_lookups": register_health_lookups,
    "real_hcpcs": download_real_hcpcs,
    "cms1500_template": download_cms1500_template,
    "synpuf": download_synpuf_sample,
    "nppes": download_nppes_sample,
    "xactimate_samples": download_xactimate_samples,
    "fema_ihp": download_fema_ihp_sample,
    "sba_loans": download_sba_loan_samples,
    "sba_forms": download_sba_forms,
    "eob_sample": download_eob_sample,
    "declarations_page_samples": download_declarations_page_samples,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=list(DATASETS) + ["all"], default="all")
    args = parser.parse_args()

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    targets = list(DATASETS) if args.dataset == "all" else [args.dataset]
    for name in targets:
        print(f"\n=== {name} ===")
        DATASETS[name]()


if __name__ == "__main__":
    main()
