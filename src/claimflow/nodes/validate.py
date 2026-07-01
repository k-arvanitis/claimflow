import claimflow.domains  # noqa: F401
from claimflow.domains.base import get as get_domain
from claimflow.state import ClaimState, ValidationFailure


def validate_node(state: ClaimState) -> dict:
    data = state.get("extraction_data") or {}
    domain_key = state.get("domain")
    domain = get_domain(domain_key) if domain_key else None

    if domain is None:
        return {"validation_failures": [
            ValidationFailure(field="domain", rule="mandatory",
                reason=f"No validator registered for domain '{domain_key}'")
        ]}

    failures = domain.validate(data)
    return {"validation_failures": failures}
