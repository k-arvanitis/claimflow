"""Evaluate ClaimFlow across all domains against synthetic ground truth.

Run: uv run python scripts/run_eval.py
     uv run python scripts/run_eval.py --domain health
     uv run python scripts/run_eval.py --packages data/synthetic/property

Writes aggregated + per-package results to output/eval_results.json.
"""
import argparse
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

import claimflow.domains  # noqa: F401 — triggers domain register() calls
from claimflow.domains.base import get as get_domain
from claimflow.graph import build_graph

# Fields to skip in scalar comparison (complex/nested or eval-irrelevant)
_SKIP_FIELDS = {"service_lines", "line_items", "diagnosis_codes", "errors"}

_DATE_FIELDS = {"patient_dob", "date_of_service", "date_of_loss", "date_of_birth"}
_CODE_HINTS = ("code", "npi", "_id", "id_number")


def _numeric_fields(domain_key: str | None) -> set[str]:
    """Field names typed float/int in the domain's Pydantic schema — the schema is the
    source of truth for "this is a number", not a guessed list of name substrings
    (which reliably misses fields like total_assets, depreciation, deductible)."""
    domain = get_domain(domain_key) if domain_key else None
    if domain is None:
        return set()
    return {
        name for name, field in domain.spec.model.model_fields.items()
        if "float" in str(field.annotation) or "int" in str(field.annotation)
    }


def _boolean_fields(domain_key: str | None) -> set[str]:
    """Field names typed bool in the domain's schema. A boolean's value stringifies to
    "True"/"False", which never literally appears on the source document (a form shows a
    checkbox mark, not the word "True") — evidence linking structurally can't ground these,
    so they're excluded from the source-evidence-accuracy metric rather than counted as
    "correct but unaudited"."""
    domain = get_domain(domain_key) if domain_key else None
    if domain is None:
        return set()
    return {
        name for name, field in domain.spec.model.model_fields.items()
        if "bool" in str(field.annotation)
    }


def _norm_date(val: str) -> str:
    """Normalise to MMDDYYYY digit string (handles MM/DD/YY, MMDDYYYY, etc.)."""
    digits = re.sub(r"\D", "", str(val))
    if len(digits) == 6:  # MMDDYY → MMDDYYYY (assume 2000s)
        return digits[:4] + "20" + digits[4:]
    return digits


def _field_type(key: str, numeric_fields: set[str]) -> str:
    if key in _DATE_FIELDS:
        return "date"
    if key in numeric_fields:
        return "currency"
    if any(h in key.lower() for h in _CODE_HINTS):
        return "code"
    return "text"


def _is_empty(val) -> bool:
    return val is None or (isinstance(val, str) and not val.strip())


def _values_match(key: str, pred_val, gt_val, numeric_fields: set[str]) -> bool:
    # None and "" both mean "no value" — ground truth uses "" for an intentionally blank
    # field, the model may correctly return None for the same thing. That's a match, not
    # a miss: don't penalize a model for correctly recognizing an absent field.
    if _is_empty(pred_val) and _is_empty(gt_val):
        return True
    if key in _DATE_FIELDS:
        return _norm_date(str(pred_val)) == _norm_date(str(gt_val))
    if key in numeric_fields:
        try:
            return Decimal(str(pred_val)) == Decimal(str(gt_val))
        except InvalidOperation:
            pass  # not actually numeric — fall through to string comparison
    return str(pred_val).strip().upper() == str(gt_val).strip().upper()


def _field_accuracy(predicted: dict, truth: dict, numeric_fields: set[str]) -> tuple[int, int, dict[str, list[int]]]:
    """Overall correct/total, plus a per-field-type breakdown: {type: [correct, total]}."""
    correct = total = 0
    by_type: dict[str, list[int]] = {}
    for key, gt_val in truth.items():
        if key in _SKIP_FIELDS:
            continue
        total += 1
        bucket = by_type.setdefault(_field_type(key, numeric_fields), [0, 0])
        bucket[1] += 1
        if _values_match(key, predicted.get(key), gt_val, numeric_fields):
            correct += 1
            bucket[0] += 1
    return correct, total, by_type


def _source_evidence_accuracy(
    predicted: dict, truth: dict, extraction_fields: list[dict],
    numeric_fields: set[str], boolean_fields: set[str],
) -> tuple[int, int]:
    """Among correctly extracted fields, how many carry source evidence (page + quote) —
    i.e. how often is a *correct* answer actually auditable back to the document.
    Boolean fields are excluded: they can't structurally carry a text quote (see
    _boolean_fields), so scoring them here would penalize a field type this metric
    doesn't apply to, not measure anything about extraction quality."""
    fields_by_name = {f["name"]: f for f in extraction_fields}
    with_evidence = correct_total = 0
    for key, gt_val in truth.items():
        if key in _SKIP_FIELDS or key in boolean_fields or key not in fields_by_name:
            continue
        if not _values_match(key, predicted.get(key), gt_val, numeric_fields):
            continue
        correct_total += 1
        if fields_by_name[key].get("evidence"):
            with_evidence += 1
    return with_evidence, correct_total


def _citation_faithfulness(policy_answers: list[dict]) -> tuple[int, int]:
    """Fraction of answers that cite at least one source.

    Proxy for faithfulness: an answer with no citations is likely hallucinated.
    Full faithfulness (answer grounded in cited text) requires a separate LLM judge.
    """
    total = len(policy_answers)
    cited = sum(1 for a in policy_answers if a.get("citations"))
    return cited, total


def _eval_dir(pkg_dir: Path, app) -> dict:
    gt_path = pkg_dir / "ground_truth.json"
    if not gt_path.exists():
        return {}
    gt = json.loads(gt_path.read_text())
    gt_fields = gt["fields"]
    gt_errors = gt["errors"]

    try:
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = app.invoke({"package_dir": str(pkg_dir), "domain": None}, config=config)
    except Exception as e:
        return {"error": str(e)}

    domain_key = result.get("domain")
    numeric_fields = _numeric_fields(domain_key)
    boolean_fields = _boolean_fields(domain_key)

    predicted = result.get("extraction_data") or {}
    c, t, by_type = _field_accuracy(predicted, gt_fields, numeric_fields)
    detected = {(f["field"], f["rule"]) for f in (result.get("validation_failures") or [])}
    caught = sum(1 for err in gt_errors if (err["field"], err["rule"]) in detected)
    cited, n_answers = _citation_faithfulness(result.get("policy_answers") or [])
    ev_with, ev_total = _source_evidence_accuracy(
        predicted, gt_fields, result.get("extraction_fields") or [], numeric_fields, boolean_fields,
    )

    claim_doc = next((d for d in (result.get("documents") or []) if d.get("doc_type") == domain_key), None)
    scanned = bool(claim_doc) and not claim_doc.get("has_text_layer", True)

    return {
        "package": pkg_dir.name,
        "correct": c,
        "total": t,
        "by_type": by_type,
        "gt_errors": gt_errors,
        "cited": cited,
        "n_answers": n_answers,
        "caught": caught,
        "evidence_with": ev_with,
        "evidence_total": ev_total,
        "scanned": scanned,
        "decision": result.get("decision"),
        "error": None,
    }


def _summarize(results: list[dict]) -> dict:
    ok = [r for r in results if not r.get("error") and r.get("total", 0) > 0]
    errors = sum(1 for r in results if r.get("error"))
    if not ok:
        return {"packages": 0, "errors": errors}

    total_c = sum(r["correct"] for r in ok)
    total_t = sum(r["total"] for r in ok)
    all_gt_errors = sum(len(r["gt_errors"]) for r in ok)
    total_caught = sum(r["caught"] for r in ok)
    total_cited = sum(r.get("cited", 0) for r in ok)
    total_answers = sum(r.get("n_answers", 0) for r in ok)
    ev_with = sum(r["evidence_with"] for r in ok)
    ev_total = sum(r["evidence_total"] for r in ok)
    clean = [r for r in ok if not r["gt_errors"]]
    false_pos = sum(1 for r in clean if r["decision"] == "needs_review")
    straight = sum(1 for r in ok if r["decision"] == "ready_for_processing")

    by_type: dict[str, list[int]] = {}
    for r in ok:
        for ftype, (c, t) in r["by_type"].items():
            bucket = by_type.setdefault(ftype, [0, 0])
            bucket[0] += c
            bucket[1] += t

    scanned_pkgs = [r for r in ok if r["scanned"]]
    digital_pkgs = [r for r in ok if not r["scanned"]]

    def _split_accuracy(pkgs: list[dict]) -> float | None:
        t = sum(r["total"] for r in pkgs)
        return sum(r["correct"] for r in pkgs) / t if t else None

    return {
        "packages": len(ok),
        "errors": errors,
        "field_accuracy": total_c / total_t if total_t else None,
        "field_accuracy_by_type": {
            ftype: {"accuracy": c / t if t else None, "correct": c, "total": t}
            for ftype, (c, t) in by_type.items()
        },
        "validation_catch_rate": total_caught / all_gt_errors if all_gt_errors else None,
        "false_positive_rate": false_pos / len(clean) if clean else None,
        "straight_through_rate": straight / len(ok),
        "citation_rate": total_cited / total_answers if total_answers else None,
        "source_evidence_accuracy": ev_with / ev_total if ev_total else None,
        "scanned_vs_born_digital": {
            "scanned": {"packages": len(scanned_pkgs), "field_accuracy": _split_accuracy(scanned_pkgs)},
            "born_digital": {"packages": len(digital_pkgs), "field_accuracy": _split_accuracy(digital_pkgs)},
        },
    }


def _print_summary(label: str, summary: dict) -> None:
    if not summary.get("packages"):
        print(f"\n{label}: no results")
        return

    print(f"\n{'='*52}")
    print(f"  {label} — {summary['packages']} packages")
    print(f"{'='*52}")
    print(f"  Field accuracy:          {summary['field_accuracy']:.1%}")
    for ftype, stats in summary["field_accuracy_by_type"].items():
        if stats["accuracy"] is not None:
            print(f"    - {ftype:<10}          {stats['accuracy']:.1%} ({stats['correct']}/{stats['total']})")
    if summary["validation_catch_rate"] is not None:
        print(f"  Validation catch rate:   {summary['validation_catch_rate']:.1%}")
    if summary["false_positive_rate"] is not None:
        print(f"  False positive rate:     {summary['false_positive_rate']:.1%}")
    print(f"  Straight-through:        {summary['straight_through_rate']:.1%}")
    if summary["source_evidence_accuracy"] is not None:
        print(f"  Source evidence accuracy:{summary['source_evidence_accuracy']:.1%}")
    if summary["citation_rate"] is not None:
        print(f"  Citation rate:           {summary['citation_rate']:.1%}")
    split = summary["scanned_vs_born_digital"]
    if split["scanned"]["packages"] or split["born_digital"]["packages"]:
        s, d = split["scanned"], split["born_digital"]
        s_acc = f"{s['field_accuracy']:.1%}" if s["field_accuracy"] is not None else "—"
        d_acc = f"{d['field_accuracy']:.1%}" if d["field_accuracy"] is not None else "—"
        print(f"  Scanned:                 {s_acc} ({s['packages']} packages)")
        print(f"  Born-digital:            {d_acc} ({d['packages']} packages)")
    if summary["errors"]:
        print(f"  Errors:                  {summary['errors']}")


DOMAIN_DIRS = {
    "health": "data/synthetic/health",
    "property": "data/synthetic/property",
    "loan": "data/synthetic/loan",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=list(DOMAIN_DIRS), default=None,
                        help="Run a single domain; omit to run all")
    parser.add_argument("--packages", type=Path, default=None,
                        help="Override package directory (implies single run)")
    args = parser.parse_args()

    app = build_graph()
    all_summaries: dict[str, dict] = {}

    if args.packages:
        pkgs = sorted(args.packages.glob("package_*"))
        results = [_eval_dir(p, app) for p in pkgs if (p / "ground_truth.json").exists()]
        summary = _summarize(results)
        _print_summary(str(args.packages), summary)
        all_summaries[str(args.packages)] = {"summary": summary, "packages": results}
    else:
        domains = [args.domain] if args.domain else list(DOMAIN_DIRS)
        for domain in domains:
            pkg_root = Path(DOMAIN_DIRS[domain])
            pkgs = sorted(pkg_root.glob("package_*"))
            if not pkgs:
                print(f"\n{domain}: no packages in {pkg_root} (run generate script first)")
                continue
            results = [_eval_dir(p, app) for p in pkgs if (p / "ground_truth.json").exists()]
            summary = _summarize(results)
            _print_summary(domain.upper(), summary)
            all_summaries[domain] = {"summary": summary, "packages": results}

    out_path = Path("output/eval_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_summaries, indent=2))
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
