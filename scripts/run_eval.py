"""Evaluate ClaimFlow against synthetic ground truth packages.

Run: uv run python scripts/run_eval.py --packages data/synthetic/
Requires: ANTHROPIC_API_KEY set, data/lookups/ populated (download_lookups.py)
"""
import argparse
import json
from pathlib import Path

from claimflow.graph import build_graph


def _field_accuracy(predicted: dict, truth: dict) -> tuple[int, int]:
    """Returns (correct, total) for scalar fields."""
    correct = total = 0
    for key, gt_val in truth.items():
        if key in ("service_lines", "diagnosis_codes", "errors"):
            continue
        pred_val = predicted.get(key)
        total += 1
        if str(pred_val).strip().upper() == str(gt_val).strip().upper():
            correct += 1
    return correct, total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packages", type=Path, default=Path("data/synthetic"))
    args = parser.parse_args()

    pkgs = sorted(args.packages.glob("package_*"))
    if not pkgs:
        print(f"No packages found in {args.packages}. Run generate_cms1500.py first.")
        return

    app = build_graph()

    total_correct = total_fields = 0
    validation_caught = validation_total = 0
    false_positives = 0
    straight_through = 0
    errors = 0

    for pkg in pkgs:
        gt_path = pkg / "ground_truth.json"
        if not gt_path.exists():
            continue
        gt = json.loads(gt_path.read_text())
        gt_fields = gt["fields"]
        gt_errors = gt["errors"]  # list of {field, rule}

        try:
            result = app.invoke({"package_dir": str(pkg)})
        except Exception as e:
            print(f"  ERROR {pkg.name}: {e}")
            errors += 1
            continue

        # Field accuracy
        predicted = result.get("extraction_data") or {}
        c, t = _field_accuracy(predicted, gt_fields)
        total_correct += c
        total_fields += t

        # Validation catch rate
        detected_rules = {(f["field"], f["rule"]) for f in (result.get("validation_failures") or [])}
        for err in gt_errors:
            validation_total += 1
            if (err["field"], err["rule"]) in detected_rules:
                validation_caught += 1

        # False positive: flagged a clean claim
        if not gt_errors and result.get("decision") == "flagged":
            false_positives += 1

        if result.get("decision") == "approved":
            straight_through += 1

    n = len(pkgs) - errors
    print(f"\n{'='*50}")
    print(f"ClaimFlow Eval — {n} packages")
    print(f"{'='*50}")
    print(f"Field extraction accuracy:  {total_correct/total_fields:.1%} ({total_correct}/{total_fields})")
    if validation_total:
        print(f"Validation catch rate:      {validation_caught/validation_total:.1%} ({validation_caught}/{validation_total})")
    clean = sum(1 for p in pkgs if not json.loads((p/'ground_truth.json').read_text())['errors'])
    print(f"False positive flag rate:   {false_positives/clean:.1%} ({false_positives}/{clean} clean claims flagged)")
    print(f"Straight-through rate:      {straight_through/n:.1%} ({straight_through}/{n} approved)")
    if errors:
        print(f"Errors:                     {errors}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
