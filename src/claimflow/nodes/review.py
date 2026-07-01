from claimflow.config import settings
from claimflow.state import ClaimState


def review_node(state: ClaimState) -> dict:
    if state.get("error") or state.get("extraction_status") == "error":
        return {"decision": "escalated", "review_reasons": [state.get("error", "extraction failed")]}

    confidence = state.get("extraction_overall_confidence") or 0.0
    failures = state.get("validation_failures") or []

    if confidence < settings.escalation_threshold:
        return {
            "decision": "escalated",
            "review_reasons": [f"Overall confidence {confidence:.0%} below escalation threshold"],
        }

    reasons = [f"{f['field']}: {f['reason']}" for f in failures]

    if failures or confidence < settings.confidence_threshold:
        if confidence < settings.confidence_threshold:
            reasons.append(f"Overall confidence {confidence:.0%} below review threshold")
        return {"decision": "flagged", "review_reasons": reasons}

    return {"decision": "approved", "review_reasons": []}
