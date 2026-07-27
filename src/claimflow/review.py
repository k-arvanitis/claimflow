"""Reviewer-edit merging, diffing, and validation-rerun logic shared by both UIs."""

import copy
import re

from claimflow.domains.base import get as get_domain
from claimflow.state import ValidationFailure

_ROW_FIELD = re.compile(r"^(?P<parent>.+)\[(?P<index>\d+)\]$")


def merge_reviewed_values(
    extraction_data: dict,
    actions: dict[str, object],
    corrected_fields: dict | None = None,
) -> dict:
    """Apply the latest reviewer actions without mutating machine extraction.

    Scalar/top-level fields are replaced or cleared directly. Synthetic row
    fields such as ``service_lines[1]`` edit/remove the corresponding row in
    their parent list. Explicit request corrections are applied last so a
    validation request can override an older persisted action.
    """
    merged = copy.deepcopy(extraction_data)
    combined_actions = dict(actions)
    for field_name, value in (corrected_fields or {}).items():
        action_name = (
            "reject" if value is None and _ROW_FIELD.match(field_name) else "edit"
        )
        combined_actions[field_name] = {"action": action_name, "corrected_value": value}

    def _parts(action: object) -> tuple[str, object]:
        if isinstance(action, dict):
            return str(action.get("action", "approve")), action.get("corrected_value")
        action_name = str(getattr(action, "action", "approve"))
        corrected_json = getattr(action, "corrected_value_json", None)
        if corrected_json is None:
            return action_name, None
        import json

        return action_name, json.loads(corrected_json)

    top_level: list[tuple[str, str, object]] = []
    row_level: list[tuple[str, int, str, object]] = []
    for field_name, action in combined_actions.items():
        action_name, corrected_value = _parts(action)
        match = _ROW_FIELD.match(field_name)
        if match:
            row_level.append(
                (
                    match.group("parent"),
                    int(match.group("index")),
                    action_name,
                    corrected_value,
                )
            )
        else:
            top_level.append((field_name, action_name, corrected_value))

    for field_name, action_name, corrected_value in top_level:
        if action_name in ("edit", "add"):
            merged[field_name] = copy.deepcopy(corrected_value)
        elif action_name == "reject":
            merged[field_name] = None

    # Removing from the highest index first preserves the original row identity.
    row_level.sort(key=lambda item: item[1], reverse=True)
    for parent, index, action_name, corrected_value in row_level:
        rows = merged.get(parent)
        if not isinstance(rows, list):
            continue
        if action_name == "reject" and 0 <= index < len(rows):
            rows.pop(index)
        elif action_name == "edit" and 0 <= index < len(rows):
            rows[index] = copy.deepcopy(corrected_value)
        elif action_name == "add":
            if index <= len(rows):
                rows.insert(index, copy.deepcopy(corrected_value))
            else:
                rows.append(copy.deepcopy(corrected_value))

    return merged


def diff_list_field(
    name: str, original: list, edited: list, fields_meta: dict, note: str | None = None
) -> dict:
    """Row-level review export for a nested/list field. For list[dict] fields,
    doc-intel's score() emits a per-row FieldConfidence entry named "name[i]"
    (see doc_intel.confidence.score) — used when present. Falls back to the
    parent field's aggregate confidence/evidence (e.g. for list[str] fields,
    which never get per-row entries) — matched by position; a row past the
    original length is "add", a row missing from the edited list is "reject"."""
    is_scalar_list = bool(original) and not isinstance(original[0], dict)
    parent_meta = fields_meta.get(name, {})
    rows = []
    for i in range(max(len(original), len(edited))):
        orig_val = original[i] if i < len(original) else None
        new_val = edited[i] if i < len(edited) else None
        if new_val is None:
            action, final_val = "reject", None
        elif orig_val is None:
            action, final_val = "add", new_val
        elif new_val == orig_val:
            action, final_val = "approve", orig_val
        else:
            action, final_val = "edit", new_val

        row_meta = fields_meta.get(f"{name}[{i}]", parent_meta)
        conf = row_meta.get("confidence")
        evidence = row_meta.get("evidence")

        if is_scalar_list:
            rows.append(
                {
                    "original_value": orig_val,
                    "final_value": final_val,
                    "action": action,
                    "confidence": conf,
                    "evidence": evidence,
                    "review_note": note,
                }
            )
        else:
            rows.append(
                {
                    "row_id": f"{name}_{i + 1}",
                    "action": action,
                    "original_value": orig_val,
                    "final_value": final_val,
                    "confidence": conf,
                    "evidence": evidence,
                    "review_note": note,
                }
            )
    return {"type": "list" if is_scalar_list else "table", "rows": rows}


def rerun_validation(domain_key: str, merged_data: dict) -> list[ValidationFailure]:
    """Re-run the domain's real deterministic validator against reviewer-edited
    values — same function the pipeline itself calls, not a reimplementation."""
    domain = get_domain(domain_key)
    if domain is None:
        return []
    return list(domain.validate(merged_data))
