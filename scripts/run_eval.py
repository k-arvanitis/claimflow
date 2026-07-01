"""Evaluate ClaimFlow across all domains against synthetic ground truth.

Run: uv run python scripts/run_eval.py
     uv run python scripts/run_eval.py --domain health
     uv run python scripts/run_eval.py --packages data/synthetic/property
"""
import argparse
import json
from pathlib import Path

from claimflow.graph import build_graph

# Fields to skip in scalar comparison (complex/nested or eval-irrelevant)
_SKIP_FIELDS = {"service_lines", "line_items", "diagnosis_codes", "errors"}


def _field_accuracy(predicted: dict, truth: dict) -> tuple[int, int]:
    correct = total = 0
    for key, gt_val in truth.items():
        if key in _SKIP_FIELDS:
            continue
        pred_val = predicted.get(key)
        total += 1
        if str(pred_val).strip().upper() == str(gt_val).strip().upper():
            correct += 1
    return correct, total


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
        result = app.invoke({"package_dir": str(pkg_dir), "domain": None})
    except Exception as e:
        return {"error": str(e)}

    predicted = result.get("extraction_data") or {}
    c, t = _field_accuracy(predicted, gt_fields)
    detected = {(f["field"], f["rule"]) for f in (result.get("validation_failures") or [])}
    caught = sum(1 for err in gt_errors if (err["field"], err["rule"]) in detected)
    cited, n_answers = _citation_faithfulness(result.get("policy_answers") or [])

    return {
        "correct": c,
        "total": t,
        "gt_errors": gt_errors,
        "cited": cited,
        "n_answers": n_answers,
        "caught": caught,
        "decision": result.get("decision"),
        "error": None,
    }


def _print_summary(label: str, results: list[dict]) -> None:
    ok = [r for r in results if not r.get("error") and r.get("total", 0) > 0]
    if not ok:
        print(f"\n{label}: no results")
        return

    total_c = sum(r["correct"] for r in ok)
    total_t = sum(r["total"] for r in ok)
    all_gt_errors = sum(len(r["gt_errors"]) for r in ok)
    total_caught = sum(r["caught"] for r in ok)
    total_cited = sum(r.get("cited", 0) for r in ok)
    total_answers = sum(r.get("n_answers", 0) for r in ok)
    clean = [r for r in ok if not r["gt_errors"]]
    false_pos = sum(1 for r in clean if r["decision"] == "flagged")
    straight = sum(1 for r in ok if r["decision"] == "approved")
    errors = sum(1 for r in results if r.get("error"))

    print(f"\n{'='*52}")
    print(f"  {label} — {len(ok)} packages")
    print(f"{'='*52}")
    print(f"  Field accuracy:        {total_c/total_t:.1%} ({total_c}/{total_t})")
    if all_gt_errors:
        print(f"  Validation catch rate: {total_caught/all_gt_errors:.1%} ({total_caught}/{all_gt_errors})")
    if clean:
        print(f"  False positive rate:   {false_pos/len(clean):.1%} ({false_pos}/{len(clean)} clean flagged)")
    print(f"  Straight-through:      {straight/len(ok):.1%} ({straight}/{len(ok)} approved)")
    if total_answers:
        print(f"  Citation rate:         {total_cited/total_answers:.1%} ({total_cited}/{total_answers} answers cited)")
    if errors:
        print(f"  Errors:                {errors}")


DOMAIN_DIRS = {
    "health": "data/synthetic",       # legacy flat layout
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

    if args.packages:
        pkgs = sorted(args.packages.glob("package_*"))
        results = [_eval_dir(p, app) for p in pkgs if (p / "ground_truth.json").exists()]
        _print_summary(str(args.packages), results)
        return

    domains = [args.domain] if args.domain else list(DOMAIN_DIRS)
    for domain in domains:
        pkg_root = Path(DOMAIN_DIRS[domain])
        pkgs = sorted(pkg_root.glob("package_*"))
        if not pkgs:
            print(f"\n{domain}: no packages in {pkg_root} (run generate script first)")
            continue
        results = [_eval_dir(p, app) for p in pkgs if (p / "ground_truth.json").exists()]
        _print_summary(domain.upper(), results)


if __name__ == "__main__":
    main()
