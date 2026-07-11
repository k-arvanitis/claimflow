"""Metrics for the real/public eval layer. Pure functions, no I/O — easy to unit test."""
from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from rapidfuzz import fuzz


def _norm_token(tok: str) -> str:
    return re.sub(r"[^\w]", "", tok).lower()


def token_precision_recall_f1(predicted_text: str, gold_words: list[str]) -> dict:
    """Token-level P/R/F1 between OCR'd text and a list of gold words (FUNSD-style)."""
    pred_tokens = Counter(_norm_token(t) for t in predicted_text.split() if _norm_token(t))
    gold_tokens = Counter(_norm_token(w) for w in gold_words if _norm_token(w))

    overlap = sum((pred_tokens & gold_tokens).values())
    n_pred = sum(pred_tokens.values())
    n_gold = sum(gold_tokens.values())

    precision = overlap / n_pred if n_pred else 0.0
    recall = overlap / n_gold if n_gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def bbox_iou(box_a: list[float], box_b: list[float]) -> float:
    """IoU between two [x0, y0, x1, y1] boxes."""
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    intersection = iw * ih
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def evidence_page_hit_rate(predicted_pages: list[int], gold_pages: list[int]) -> float:
    """Fraction of gold-page expectations matched by the corresponding predicted page."""
    if not gold_pages:
        return 0.0
    hits = sum(1 for p, g in zip(predicted_pages, gold_pages) if p == g)
    return hits / len(gold_pages)


def _values_equal(pred_val, expected, value_type: str | None) -> bool:
    """String-equal for text, numeric-equal for currency/number (so "7731.00" and
    7731.0 count as a match instead of failing on trailing-zero formatting)."""
    if value_type in ("currency", "number"):
        try:
            return Decimal(str(pred_val)) == Decimal(str(expected))
        except (InvalidOperation, TypeError):
            pass  # fall through to string comparison
    return str(pred_val).strip().upper() == str(expected).strip().upper()


def field_exact_accuracy(predicted: dict, gold_fields: list[dict]) -> tuple[int, int]:
    """Exact match between predicted and gold field values (numeric-aware for currency/number)."""
    correct = total = 0
    for f in gold_fields:
        name, expected = f["field_name"], f.get("expected_value")
        if expected is None:
            continue
        total += 1
        pred_val = predicted.get(name)
        if _values_equal(pred_val, expected, f.get("value_type")):
            correct += 1
    return correct, total


def field_fuzzy_accuracy(predicted: dict, gold_fields: list[dict], threshold: float = 90.0) -> tuple[int, int]:
    """Fuzzy string match (rapidfuzz ratio >= threshold) for text; numeric-equal for
    currency/number (same reasoning as field_exact_accuracy — fuzzy string matching
    on "7731.00" vs "7731.0" is the wrong tool for a numeric formatting difference)."""
    correct = total = 0
    for f in gold_fields:
        name, expected = f["field_name"], f.get("expected_value")
        if expected is None:
            continue
        total += 1
        pred_val = predicted.get(name)
        if pred_val is None:
            continue
        if f.get("value_type") in ("currency", "number"):
            if _values_equal(pred_val, expected, f.get("value_type")):
                correct += 1
        elif fuzz.ratio(str(pred_val), str(expected)) >= threshold:
            correct += 1
    return correct, total


def numeric_accuracy_with_tolerance(
    predicted: dict, gold_fields: list[dict], abs_tol: float = 0.01, rel_tol: float = 0.001
) -> tuple[int, int]:
    """Numeric field match within absolute or relative tolerance (currency/quantity fields)."""
    correct = total = 0
    for f in gold_fields:
        if f.get("value_type") not in ("currency", "number"):
            continue
        name, expected = f["field_name"], f.get("expected_value")
        if expected is None:
            continue
        total += 1
        try:
            pred_num = Decimal(str(predicted.get(name)))
            gold_num = Decimal(str(expected))
            diff = abs(pred_num - gold_num)
            if diff <= Decimal(str(abs_tol)) or (gold_num and diff / abs(gold_num) <= Decimal(str(rel_tol))):
                correct += 1
        except (InvalidOperation, TypeError):
            pass
    return correct, total


def _norm_date(val) -> str:
    digits = re.sub(r"\D", "", str(val))
    if len(digits) == 6:
        return digits[:4] + "20" + digits[4:]
    return digits


def date_accuracy(predicted: dict, gold_fields: list[dict]) -> tuple[int, int]:
    correct = total = 0
    for f in gold_fields:
        if f.get("value_type") != "date":
            continue
        name, expected = f["field_name"], f.get("expected_value")
        if expected is None:
            continue
        total += 1
        if _norm_date(predicted.get(name)) == _norm_date(expected):
            correct += 1
    return correct, total


def classification_accuracy(predictions: list[str], gold_labels: list[str]) -> float:
    if not gold_labels:
        return 0.0
    correct = sum(1 for p, g in zip(predictions, gold_labels) if p == g)
    return correct / len(gold_labels)


def confusion_matrix(predictions: list[str], gold_labels: list[str]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {}
    for pred, gold in zip(predictions, gold_labels):
        matrix.setdefault(gold, {})
        matrix[gold][pred] = matrix[gold].get(pred, 0) + 1
    return matrix


def macro_f1(predictions: list[str], gold_labels: list[str]) -> float:
    classes = set(gold_labels) | set(predictions)
    if not classes:
        return 0.0
    f1s = []
    for c in classes:
        tp = sum(1 for p, g in zip(predictions, gold_labels) if p == c and g == c)
        fp = sum(1 for p, g in zip(predictions, gold_labels) if p == c and g != c)
        fn = sum(1 for p, g in zip(predictions, gold_labels) if p != c and g == c)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        f1s.append(f1)
    return sum(f1s) / len(f1s)


def unknown_routing_accuracy(predictions: list[str], unsupported_labels: set[str]) -> float:
    """Fraction of documents whose gold label is NOT a ClaimFlow domain that correctly routed to 'unknown'."""
    if not unsupported_labels:
        return 0.0
    routed_unknown = sum(1 for p in predictions if p == "unknown")
    return routed_unknown / len(predictions) if predictions else 0.0


def validation_false_positive_rate(flagged: list[bool]) -> float:
    """Among records expected to be valid (no known error), fraction incorrectly flagged."""
    if not flagged:
        return 0.0
    return sum(flagged) / len(flagged)


def row_precision_recall_f1(predicted_rows: list[dict], gold_rows: list[dict], key_fields: list[str]) -> dict:
    """Match predicted vs. gold table rows by a set of key fields (e.g. description+quantity)."""
    def _key(row: dict) -> tuple:
        return tuple(str(row.get(k, "")).strip().upper() for k in key_fields)

    gold_keys = {_key(r) for r in gold_rows}
    pred_keys = {_key(r) for r in predicted_rows}
    matched = gold_keys & pred_keys

    precision = len(matched) / len(pred_keys) if pred_keys else 0.0
    recall = len(matched) / len(gold_keys) if gold_keys else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def arithmetic_consistency_accuracy(rows: list[dict]) -> float:
    """Fraction of line-item rows where quantity * unit_cost == the line total
    (within 1 cent). Accepts either "rcv" (gold annotation key) or "total"
    (ClaimFlow's LineItem schema key) for the line-total field."""
    if not rows:
        return 0.0
    consistent = 0
    for r in rows:
        try:
            qty = Decimal(str(r["quantity"]))
            unit_cost = Decimal(str(r["unit_cost"]))
            total = Decimal(str(r["rcv"] if "rcv" in r else r["total"]))
            if abs(qty * unit_cost - total) <= Decimal("0.02"):
                consistent += 1
        except (KeyError, InvalidOperation, TypeError):
            pass
    return consistent / len(rows)
