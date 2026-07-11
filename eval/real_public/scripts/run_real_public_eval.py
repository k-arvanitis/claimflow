"""Run ClaimFlow's real doc-intel extraction against the 3 real Xactimate sample PDFs
and score against hand-written gold annotations. Reuses the actual production
extraction path (claimflow.domains.property's XactimatePDF spec via doc-intel),
not a reimplementation.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from metrics import (  # noqa: E402
    arithmetic_consistency_accuracy,
    date_accuracy,
    field_exact_accuracy,
    field_fuzzy_accuracy,
    numeric_accuracy_with_tolerance,
    row_precision_recall_f1,
)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
GOLD_DIR = Path(__file__).parent.parent / "datasets" / "property" / "gold"
PDF_DIR = _REPO_ROOT / "data" / "real_public" / "property" / "xactimate_samples"
RESULTS_DIR = Path(__file__).parent.parent / "results"


def _run_xactimate_extraction() -> list[dict]:
    from doc_intel.extract import extract

    from claimflow.domains.property import PROPERTY

    rows = []
    for gold_path in sorted(GOLD_DIR.glob("*.json")):
        gold = json.loads(gold_path.read_text())
        if gold.get("expected_classification") != "xactimate":
            continue  # property/gold/ also holds the declarations-page case study's gold file
        doc_id = gold["doc_id"]
        pdf_path = PDF_DIR / f"{doc_id}.pdf"

        start = time.monotonic()
        try:
            result = extract(str(pdf_path), PROPERTY.spec)
            # extract() never raises -- on internal failure it returns status="error"
            # with empty data instead, so a successful Python call doesn't mean success.
            error = result.source_meta.get("error") if result.status == "error" else None
            predicted = result.data
        except Exception as e:
            error = str(e)
            predicted = {}
        latency_ms = (time.monotonic() - start) * 1000

        exact_c, exact_t = field_exact_accuracy(predicted, gold["fields"])
        fuzzy_c, fuzzy_t = field_fuzzy_accuracy(predicted, gold["fields"])
        numeric_c, numeric_t = numeric_accuracy_with_tolerance(predicted, gold["fields"])
        date_c, date_t = date_accuracy(predicted, gold["fields"])

        gold_rows = gold["tables"][0]["rows"] if gold["tables"] else []
        pred_rows = predicted.get("line_items") or []
        row_scores = row_precision_recall_f1(pred_rows, gold_rows, key_fields=["description", "quantity"])
        arithmetic_acc = arithmetic_consistency_accuracy(pred_rows)

        # Real call into the production deterministic validator, not a reimplementation.
        # No hand-labeled expected-failures gold for these 3 docs -- reporting raw
        # pass/fail + reasons, not a catch-rate percentage (would be false precision on n=3).
        validation_failures = PROPERTY.validate(predicted) if predicted else []

        rows.append({
            "run_id": "phase_e_xactimate",
            "dataset": "public_xactimate",
            "doc_id": doc_id,
            "domain": "property",
            "task_type": "extraction",
            "metric_group": "field_and_table",
            "passed": error is None,
            "scores": {
                "field_exact_accuracy": exact_c / exact_t if exact_t else None,
                "field_exact_checked": exact_t,
                "field_fuzzy_accuracy": fuzzy_c / fuzzy_t if fuzzy_t else None,
                "numeric_accuracy_with_tolerance": numeric_c / numeric_t if numeric_t else None,
                "date_accuracy": date_c / date_t if date_t else None,
                "line_item_row_f1": row_scores["f1"],
                "line_item_row_precision": row_scores["precision"],
                "line_item_row_recall": row_scores["recall"],
                "arithmetic_consistency_accuracy": arithmetic_acc,
            },
            "prediction": predicted,
            "gold": gold,
            "validation_failures": validation_failures,
            "failure_category": None,
            "error": error,
            "latency_ms": round(latency_ms, 1),
        })
        print(f"{doc_id}: exact={exact_c}/{exact_t} fuzzy={fuzzy_c}/{fuzzy_t} "
              f"row_f1={row_scores['f1']:.2f} validation_failures={len(validation_failures)} "
              f"latency={latency_ms:.0f}ms error={error}")
    return rows


def _run_single_doc_case_study(doc_id: str, domain, pdf_path: Path, gold_path: Path, dataset: str) -> dict:
    """Single-document extraction case study (n=1) — EOB and declarations page have no
    line-item table, so this is the scalar-fields-only subset of the Xactimate function
    above. Explicitly n=1: reported as a case study, never averaged into a headline rate."""
    from doc_intel.extract import extract

    gold = json.loads(gold_path.read_text())
    start = time.monotonic()
    try:
        result = extract(str(pdf_path), domain.spec)
        error = result.source_meta.get("error") if result.status == "error" else None
        predicted = result.data
    except Exception as e:
        error = str(e)
        predicted = {}
    latency_ms = (time.monotonic() - start) * 1000

    exact_c, exact_t = field_exact_accuracy(predicted, gold["fields"])
    fuzzy_c, fuzzy_t = field_fuzzy_accuracy(predicted, gold["fields"])
    numeric_c, numeric_t = numeric_accuracy_with_tolerance(predicted, gold["fields"])
    date_c, date_t = date_accuracy(predicted, gold["fields"])
    validation_failures = domain.validate(predicted) if predicted else []

    row = {
        "run_id": "phase_g_case_study",
        "dataset": dataset,
        "doc_id": doc_id,
        "domain": gold["domain"],
        "task_type": "extraction",
        "metric_group": "field_only",
        "passed": error is None,
        "scores": {
            "field_exact_accuracy": exact_c / exact_t if exact_t else None,
            "field_exact_checked": exact_t,
            "field_fuzzy_accuracy": fuzzy_c / fuzzy_t if fuzzy_t else None,
            "numeric_accuracy_with_tolerance": numeric_c / numeric_t if numeric_t else None,
            "date_accuracy": date_c / date_t if date_t else None,
        },
        "prediction": predicted,
        "gold": gold,
        "validation_failures": validation_failures,
        "error": error,
        "latency_ms": round(latency_ms, 1),
    }
    print(f"{doc_id}: exact={exact_c}/{exact_t} fuzzy={fuzzy_c}/{fuzzy_t} "
          f"validation_failures={len(validation_failures)} latency={latency_ms:.0f}ms error={error}")
    return row


def _run_eob_case_study() -> dict:
    from claimflow.domains.health import EOB_DOMAIN

    pdf_path = _REPO_ROOT / "data" / "real_public" / "health" / "cms_sample_eob.pdf"
    gold_path = Path(__file__).parent.parent / "datasets" / "health" / "gold" / "cms_sample_eob.json"
    return _run_single_doc_case_study("cms_sample_eob", EOB_DOMAIN, pdf_path, gold_path, "cms_sample_eob")


def _run_declarations_page_case_study() -> dict:
    from claimflow.domains.property import DECLARATIONS_PAGE

    pdf_path = _REPO_ROOT / "data" / "real_public" / "property" / "florida_cfo_sample_declarations.pdf"
    gold_path = (
        Path(__file__).parent.parent / "datasets" / "property" / "gold"
        / "florida_cfo_sample_declarations.json"
    )
    return _run_single_doc_case_study(
        "florida_cfo_sample_declarations", DECLARATIONS_PAGE, pdf_path, gold_path, "public_declarations_page",
    )


def main() -> None:
    rows = _run_xactimate_extraction()
    case_study_rows = [_run_eob_case_study(), _run_declarations_page_case_study()]
    all_rows = rows + case_study_rows

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = RESULTS_DIR / "extraction_results.jsonl"
    with open(jsonl_path, "w") as f:
        for row in all_rows:
            f.write(json.dumps(row, default=str) + "\n")

    summary = {
        "n_documents": len(rows),
        "n_errors": sum(1 for r in rows if r["error"]),
        "mean_field_exact_accuracy": (
            sum(r["scores"]["field_exact_accuracy"] or 0 for r in rows) / len(rows) if rows else None
        ),
        "mean_line_item_row_f1": sum(r["scores"]["line_item_row_f1"] for r in rows) / len(rows) if rows else None,
        "validation_failures_by_doc": {r["doc_id"]: r["validation_failures"] for r in rows},
        "additional_case_studies_n1": {
            r["doc_id"]: {
                "field_exact_accuracy": r["scores"]["field_exact_accuracy"],
                "validation_failures": r["validation_failures"],
                "error": r["error"],
            }
            for r in case_study_rows
        },
    }
    summary_path = RESULTS_DIR / "extraction_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWritten: {jsonl_path}\nWritten: {summary_path}")


if __name__ == "__main__":
    main()
