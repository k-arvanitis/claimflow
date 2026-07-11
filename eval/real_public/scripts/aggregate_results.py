"""Combine every phase's individual result file into one top-level results/summary.json.
Run after health/property/loan/extraction scripts have produced their own outputs."""
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "results"

SOURCES = {
    "health": "health_public_summary.json",
    "property": "property_public_summary.json",
    "loan": "loan_public_summary.json",
    "xactimate_extraction": "extraction_summary.json",
}


def main() -> None:
    combined = {}
    missing = []
    for key, filename in SOURCES.items():
        path = RESULTS_DIR / filename
        if path.exists():
            combined[key] = json.loads(path.read_text())
        else:
            missing.append(filename)

    if missing:
        combined["_missing"] = missing

    out_path = RESULTS_DIR / "summary.json"
    out_path.write_text(json.dumps(combined, indent=2))
    print(f"Written: {out_path}")
    if missing:
        print(f"Note: missing source files (run their scripts first): {missing}")


if __name__ == "__main__":
    main()
