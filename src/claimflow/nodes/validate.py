import claimflow.domains  # noqa: F401
from claimflow.domains.base import get as get_domain
from claimflow.state import ClaimState, ValidationFailure


def validate_node(state: ClaimState) -> dict:
    data = state.get("extraction_data") or {}
    domain_key = state.get("domain")
    domain = get_domain(domain_key) if domain_key else None

    if domain is None:
        return {
            "validation_failures": [
                ValidationFailure(
                    field="domain",
                    rule="mandatory",
                    reason=f"No validator registered for domain '{domain_key}'",
                    severity="error",
                    policy_required=False,
                )
            ]
        }

    failures = domain.validate(data)
    failures.extend(_validate_secondary_extractions(state))
    return {"validation_failures": failures}


def _validate_secondary_extractions(state: ClaimState) -> list[ValidationFailure]:
    """
    Run each secondary document's own domain validator against its own
    extracted data, tagging failures with the doc_type so a reviewer can
    tell which document a failure came from. Skips documents whose
    extraction failed — nothing to validate.
    """
    failures: list[ValidationFailure] = []
    for extraction in state.get("secondary_extractions") or []:
        if extraction["status"] == "error":
            continue
        sub_domain = get_domain(extraction["doc_type"])
        if sub_domain is None:
            continue
        for failure in sub_domain.validate(extraction["data"] or {}):
            tagged = dict(failure)
            tagged["field"] = f"{extraction['doc_type']}: {failure['field']}"
            failures.append(tagged)
    return failures
