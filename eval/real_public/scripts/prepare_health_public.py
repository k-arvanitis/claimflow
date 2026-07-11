"""Validation-layer eval for the health domain against real CMS SynPUF claims.

SynPUF is claim-level (not itemized CMS-1500 service lines) and predates ICD-10
(diagnosis codes are ICD-9, e.g. "V5841") — so this does NOT run SynPUF rows through
domains/health.py's full _validate() (that expects CMS-1500 box-shaped fields SynPUF
doesn't have, like insurance_id/total_charge/patient_name). Instead it checks what
SynPUF *does* provide against real reference data: HCPCS procedure codes (against a
real HCPCS Level II lookup, NOT production's synthetic cpt.csv placeholder), NPIs,
and claim date ordering. ICD-9 diagnosis codes are explicitly skipped — validating
them against our ICD-10 lookup would reject every single one and misrepresent a
code-system era mismatch as a validator failure.

SynPUF's HCPCS_CD_* fields also mix in plain numeric CPT-style codes (e.g. "85610",
lab procedure codes) alongside genuine alphanumeric HCPCS Level II codes (e.g.
"J2501"). A pure HCPCS Level II lookup correctly does NOT contain numeric CPT codes
(that's licensed AMA content, a different code set) — so numeric and alphanumeric
codes are scored separately below rather than lumped into one rate that would look
like a validator failure when it's actually the same code-system-scope issue as ICD-9.
"""
import csv
import json
import re
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
SYNPUF_PATH = _REPO_ROOT / "data" / "real_public" / "health" / "synpuf" / "DE1_0_2008_to_2010_Outpatient_Claims_Sample_1.csv"
HCPCS_REAL_PATH = _REPO_ROOT / "data" / "real_public" / "health" / "hcpcs_real.csv"
NPPES_PATH = _REPO_ROOT / "data" / "real_public" / "health" / "nppes_sample.json"
N_SAMPLE = 500


def _load_real_hcpcs_codes() -> set[str]:
    codes = set()
    with open(HCPCS_REAL_PATH) as f:
        next(f)
        for line in f:
            codes.add(line.split(",")[0].strip())
    return codes


def _npi_looks_valid(npi: str) -> bool:
    return bool(re.fullmatch(r"\d{10}", npi))


def _parse_synpuf_date(val: str) -> date | None:
    if not val or len(val) != 8:
        return None
    try:
        return date(int(val[:4]), int(val[4:6]), int(val[6:8]))
    except ValueError:
        return None


def run() -> dict:
    real_hcpcs = _load_real_hcpcs_codes()
    rows = []
    with open(SYNPUF_PATH) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= N_SAMPLE:
                break
            rows.append(row)

    alpha_total = alpha_valid = 0
    numeric_total = 0
    npi_total = npi_valid = 0
    date_total = date_valid = 0

    for row in rows:
        for i in range(1, 46):
            code = row.get(f"HCPCS_CD_{i}", "").strip()
            if not code:
                continue
            if re.fullmatch(r"\d{5}", code):
                numeric_total += 1  # CPT-range code — out of scope for a pure HCPCS lookup
            else:
                alpha_total += 1
                if code in real_hcpcs:
                    alpha_valid += 1

        npi = row.get("AT_PHYSN_NPI", "").strip()
        if npi:
            npi_total += 1
            if _npi_looks_valid(npi):
                npi_valid += 1

        frm = _parse_synpuf_date(row.get("CLM_FROM_DT", ""))
        thru = _parse_synpuf_date(row.get("CLM_THRU_DT", ""))
        if frm and thru:
            date_total += 1
            if frm <= thru <= date.today():
                date_valid += 1

    summary = {
        "dataset": "cms_synpuf",
        "n_claims_sampled": len(rows),
        "hcpcs_alphanumeric_code_acceptance_rate": alpha_valid / alpha_total if alpha_total else None,
        "hcpcs_alphanumeric_codes_checked": alpha_total,
        "cpt_range_numeric_codes_seen_but_out_of_scope": numeric_total,
        "npi_format_validity_rate": npi_valid / npi_total if npi_total else None,
        "npis_checked": npi_total,
        "date_ordering_validity_rate": date_valid / date_total if date_total else None,
        "dates_checked": date_total,
        "skipped": {
            "icd9_diagnosis_codes": (
                "SynPUF diagnosis codes are ICD-9 (2008-2010 data, predates the 2015 ICD-10 "
                "transition); validating them against ClaimFlow's ICD-10 lookup would reject "
                "every code and misrepresent a code-system era mismatch as a validator failure."
            ),
            "cpt_range_numeric_codes": (
                "SynPUF's HCPCS_CD_* fields also contain plain numeric CPT-style codes (e.g. lab "
                "procedure codes). A real HCPCS Level II lookup correctly excludes these (AMA-"
                "licensed CPT-4 content, a different code set) — counted above but not scored "
                "as pass/fail, same reasoning as the ICD-9 skip."
            ),
        },
    }
    return summary


def run_nppes_check() -> dict:
    """Phase F: run real, currently-active NPPES NPIs through ClaimFlow's actual
    NPI format/fabrication-pattern check (reused directly from domains/health.py,
    not reimplemented). All 30 records are real, active provider registrations —
    the NPI Registry search API only returned active status in this sample, so
    deactivated-NPI detection isn't exercised here (noted honestly, not faked)."""
    from claimflow.domains.health import _looks_fabricated

    records = json.loads(NPPES_PATH.read_text())
    total = len(records)
    format_valid = 0
    not_flagged_as_fabricated = 0

    for r in records:
        npi = str(r["number"])
        if re.fullmatch(r"\d{10}", npi):
            format_valid += 1
        if not _looks_fabricated(npi):
            not_flagged_as_fabricated += 1

    return {
        "dataset": "nppes",
        "n_npis_checked": total,
        "npi_format_valid_rate": format_valid / total if total else None,
        "not_flagged_as_fabricated_rate": not_flagged_as_fabricated / total if total else None,
        "all_records_active_status": all(r["basic"].get("status") == "A" for r in records),
        "skipped": {
            "deactivated_npi_detection": (
                "The NPI Registry search API used to fetch this sample only returned "
                "active (status='A') records; no deactivated NPIs were available to test "
                "rejection against. Not fabricated to fill the gap."
            ),
        },
    }


def run_template_layout_check() -> dict:
    """Phase G: run the official blank CMS-1500 template through extraction. Since
    the form is completely blank, ANY non-null value returned for a field is by
    definition fabricated — a direct, unambiguous test of the fabrication issue
    found earlier this session (models sometimes guess instead of returning null)."""
    from doc_intel.extract import extract

    from claimflow.domains.health import HEALTH

    template_path = _REPO_ROOT / "data" / "real_public" / "health" / "cms1500_template.pdf"
    result = extract(str(template_path), HEALTH.spec)

    non_null_fields = {k: v for k, v in result.data.items() if v not in (None, "", [], {})}
    total_fields = len(result.data)

    return {
        "dataset": "cms1500_official_template",
        "status": result.status,
        "total_fields": total_fields,
        "fabricated_field_count": len(non_null_fields),
        "blank_field_abstention_rate": (
            (total_fields - len(non_null_fields)) / total_fields if total_fields else None
        ),
        "fabricated_fields": non_null_fields,
    }


if __name__ == "__main__":
    synpuf_result = run()
    nppes_result = run_nppes_check()
    template_result = run_template_layout_check()
    combined = {"synpuf": synpuf_result, "nppes": nppes_result, "cms1500_template": template_result}
    print(json.dumps(combined, indent=2))
    out_path = Path(__file__).parent.parent / "results" / "health_public_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(combined, indent=2))
    print(f"\nWritten to {out_path}")
