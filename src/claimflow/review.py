"""Reviewer-edit diffing and validation-rerun logic, used by the Streamlit review UI.
Kept separate from streamlit_app.py so it can be unit tested without a Streamlit context."""
from claimflow.domains.base import get as get_domain
from claimflow.state import ValidationFailure


def diff_list_field(name: str, original: list, edited: list, fields_meta: dict, note: str | None = None) -> dict:
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
            rows.append({
                "original_value": orig_val, "final_value": final_val, "action": action,
                "confidence": conf, "evidence": evidence, "review_note": note,
            })
        else:
            rows.append({
                "row_id": f"{name}_{i + 1}", "action": action,
                "original_value": orig_val, "final_value": final_val,
                "confidence": conf, "evidence": evidence, "review_note": note,
            })
    return {"type": "list" if is_scalar_list else "table", "rows": rows}


def rerun_validation(domain_key: str, merged_data: dict) -> list[ValidationFailure]:
    """Re-run the domain's real deterministic validator against reviewer-edited
    values — same function the pipeline itself calls, not a reimplementation."""
    domain = get_domain(domain_key)
    if domain is None:
        return []
    return list(domain.validate(merged_data))
