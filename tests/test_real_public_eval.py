"""Mocked/offline tests for the real/public eval layer — no live downloads, no LLM calls."""
import json
import sys
from pathlib import Path

import jsonschema
import pytest

_EVAL_ROOT = Path(__file__).parent.parent / "eval" / "real_public"
sys.path.insert(0, str(_EVAL_ROOT / "scripts"))

import metrics as m  # noqa: E402

# ── Schema validation ────────────────────────────────────────────────────────

def _load_schema(name: str) -> dict:
    return json.loads((_EVAL_ROOT / "schema" / name).read_text())


def test_manifest_schema_accepts_real_manifest():
    schema = _load_schema("manifest.schema.json")
    manifest_path = _EVAL_ROOT / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("manifest.json not present in this checkout")
    manifest = json.loads(manifest_path.read_text())
    jsonschema.validate(manifest, schema)


def test_manifest_schema_rejects_missing_required_field():
    schema = _load_schema("manifest.schema.json")
    bad_entry = [{"doc_id": "x", "dataset": "y"}]  # missing required fields
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad_entry, schema)


def test_manifest_schema_rejects_bad_sha256_format():
    schema = _load_schema("manifest.schema.json")
    entry = {
        "doc_id": "x", "dataset": "y", "domain": "health", "document_type": "z",
        "source_url": "https://example.com", "local_path": "a/b", "accessed_at": "2026-01-01T00:00:00Z",
        "sha256": "not-a-real-hash", "license_public_use_notes": "n", "pii_status": "public_non_pii",
        "split": "test",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate([entry], schema)


def test_gold_fields_schema_accepts_real_gold_files():
    schema = _load_schema("gold_fields.schema.json")
    gold_files = [
        p for domain in ("health", "property", "loan")
        for p in (_EVAL_ROOT / "datasets" / domain / "gold").glob("*.json")
    ]
    assert gold_files, "expected at least one gold annotation file"
    for path in gold_files:
        jsonschema.validate(json.loads(path.read_text()), schema)


def test_gold_fields_schema_rejects_bad_task_type():
    schema = _load_schema("gold_fields.schema.json")
    bad = {"doc_id": "x", "domain": "property", "task_type": "not_a_real_task_type"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_results_schema_accepts_minimal_row():
    schema = _load_schema("results.schema.json")
    row = {
        "run_id": "r1", "dataset": "d", "doc_id": "x", "domain": "property",
        "task_type": "extraction", "passed": True,
    }
    jsonschema.validate(row, schema)


# ── sha256 / manifest helpers ────────────────────────────────────────────────

def test_sha256_matches_known_value(tmp_path):
    from download_real_public import _sha256

    path = tmp_path / "f.txt"
    path.write_bytes(b"hello world")
    # Known SHA-256 test vector for the literal bytes b"hello world".
    assert _sha256(path) == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_manifest_upsert_replaces_existing_entry(tmp_path, monkeypatch):
    import download_real_public as dl

    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(dl, "_MANIFEST_PATH", manifest_path)

    dl._upsert_manifest_entry({"doc_id": "a", "value": 1})
    dl._upsert_manifest_entry({"doc_id": "b", "value": 2})
    dl._upsert_manifest_entry({"doc_id": "a", "value": 99})  # replaces, not duplicates

    entries = dl._load_manifest()
    assert len(entries) == 2
    a = next(e for e in entries if e["doc_id"] == "a")
    assert a["value"] == 99


def test_load_manifest_returns_empty_list_when_missing(tmp_path, monkeypatch):
    import download_real_public as dl

    monkeypatch.setattr(dl, "_MANIFEST_PATH", tmp_path / "does_not_exist.json")
    assert dl._load_manifest() == []


# ── Metrics — pure functions, no I/O ─────────────────────────────────────────

def test_token_precision_recall_f1_perfect_match():
    r = m.token_precision_recall_f1("the quick brown fox", ["the", "quick", "brown", "fox"])
    assert r["precision"] == 1.0
    assert r["recall"] == 1.0
    assert r["f1"] == 1.0


def test_token_precision_recall_f1_no_overlap():
    r = m.token_precision_recall_f1("aaa bbb", ["ccc", "ddd"])
    assert r["precision"] == 0.0
    assert r["recall"] == 0.0


def test_bbox_iou_identical_boxes():
    assert m.bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0


def test_bbox_iou_no_overlap():
    assert m.bbox_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def test_field_exact_accuracy_counts_correctly():
    gold = [{"field_name": "a", "expected_value": "X"}, {"field_name": "b", "expected_value": "Y"}]
    correct, total = m.field_exact_accuracy({"a": "X", "b": "Z"}, gold)
    assert (correct, total) == (1, 2)


def test_field_exact_accuracy_skips_null_gold_values():
    gold = [{"field_name": "a", "expected_value": None}]
    correct, total = m.field_exact_accuracy({"a": "anything"}, gold)
    assert (correct, total) == (0, 0)


def test_numeric_accuracy_with_tolerance_accepts_within_tolerance():
    gold = [{"field_name": "amt", "expected_value": "100.00", "value_type": "currency"}]
    correct, total = m.numeric_accuracy_with_tolerance({"amt": 100.005}, gold)
    assert (correct, total) == (1, 1)


def test_numeric_accuracy_with_tolerance_rejects_real_mismatch():
    gold = [{"field_name": "amt", "expected_value": "100.00", "value_type": "currency"}]
    correct, total = m.numeric_accuracy_with_tolerance({"amt": 500.00}, gold)
    assert (correct, total) == (0, 1)


def test_arithmetic_consistency_accepts_rcv_or_total_key():
    rows_rcv = [{"quantity": 2, "unit_cost": 5, "rcv": 10}]
    rows_total = [{"quantity": 2, "unit_cost": 5, "total": 10}]
    assert m.arithmetic_consistency_accuracy(rows_rcv) == 1.0
    assert m.arithmetic_consistency_accuracy(rows_total) == 1.0


def test_arithmetic_consistency_detects_real_mismatch():
    rows = [{"quantity": 2, "unit_cost": 5, "total": 999}]
    assert m.arithmetic_consistency_accuracy(rows) == 0.0


def test_classification_accuracy_and_macro_f1():
    preds = ["a", "b", "a", "unknown"]
    gold = ["a", "b", "b", "unknown"]
    assert m.classification_accuracy(preds, gold) == 0.75
    assert 0.0 < m.macro_f1(preds, gold) < 1.0


def test_row_precision_recall_f1_exact_match():
    gold = [{"description": "x", "quantity": 5}]
    pred = [{"description": "x", "quantity": 5}]
    r = m.row_precision_recall_f1(pred, gold, key_fields=["description", "quantity"])
    assert r == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
