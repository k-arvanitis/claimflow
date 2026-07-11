"""Validation-layer eval for the property domain against real FEMA IHP disaster
registration data. Like SynPUF, FEMA IHP is structured (JSON), so no LLM extraction
or manual gold-labeling is needed — the real dollar amounts, dates, and eligibility
flags are the test. This checks real-world amount sanity, date ordering, and a
genuine cross-field consistency rule (ineligible => zero payout), all against
public, PII-scrubbed FEMA data.
"""
import json
import re
from datetime import date, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
FEMA_PATH = _REPO_ROOT / "data" / "real_public" / "property" / "fema_ihp_sample.json"

_AMOUNT_FIELDS = [
    "ihpAmount", "haAmount", "onaAmount", "repairAmount", "replacementAmount",
    "personalPropertyAmount", "rentalAssistanceAmount", "rpfvl", "ppfvl",
]


def _parse_fema_date(val) -> date | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def run() -> dict:
    records = json.loads(FEMA_PATH.read_text())

    amount_total = amount_valid = 0
    date_total = date_valid = 0
    state_total = state_valid = 0
    zip_total = zip_valid = 0
    consistency_total = consistency_valid = 0

    for r in records:
        for field in _AMOUNT_FIELDS:
            val = r.get(field)
            if val is not None:
                amount_total += 1
                if isinstance(val, (int, float)) and val >= 0:
                    amount_valid += 1

        declared = _parse_fema_date(r.get("declarationDate"))
        applied = _parse_fema_date(r.get("appliedDate"))
        if declared and applied:
            date_total += 1
            if declared <= applied <= date.today():
                date_valid += 1

        state = r.get("damagedStateAbbreviation")
        if state:
            state_total += 1
            if re.fullmatch(r"[A-Z]{2}", state):
                state_valid += 1

        zipcode = r.get("damagedZipCode")
        if zipcode:
            zip_total += 1
            if re.fullmatch(r"\d{5}(-\d{4})?", str(zipcode)):
                zip_valid += 1

        # Cross-field consistency: not eligible for IHP => zero IHP payout
        if r.get("ihpEligible") is not None and r.get("ihpAmount") is not None:
            consistency_total += 1
            if r["ihpEligible"] or r["ihpAmount"] == 0:
                consistency_valid += 1

    return {
        "dataset": "fema_ihp",
        "n_records": len(records),
        "amount_sanity_rate": amount_valid / amount_total if amount_total else None,
        "amounts_checked": amount_total,
        "date_ordering_validity_rate": date_valid / date_total if date_total else None,
        "dates_checked": date_total,
        "state_abbreviation_format_rate": state_valid / state_total if state_total else None,
        "zip_format_rate": zip_valid / zip_total if zip_total else None,
        "ihp_eligibility_amount_consistency_rate": (
            consistency_valid / consistency_total if consistency_total else None
        ),
        "consistency_checks": consistency_total,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
    out_path = Path(__file__).parent.parent / "results" / "property_public_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nWritten to {out_path}")
