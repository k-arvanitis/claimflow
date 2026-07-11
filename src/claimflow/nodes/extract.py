import os

from claimflow.config import settings  # noqa: E402 (must precede doc-intel import)

os.environ["DOC_INTEL_PROVIDER"] = settings.doc_intel_provider
os.environ["DOC_INTEL_MODEL"] = settings.doc_intel_model
if settings.doc_intel_llm_base_url:
    os.environ["DOC_INTEL_LLM_BASE_URL"] = settings.doc_intel_llm_base_url

from doc_intel.extract import extract  # noqa: E402

import claimflow.domains  # noqa: F401, E402
from claimflow.domains.base import get as get_domain  # noqa: E402
from claimflow.state import ClaimState  # noqa: E402


def extract_node(state: ClaimState) -> dict:
    domain_key = state.get("domain")
    if not domain_key:
        return {"error": "No supported domain detected in package", "extraction_status": "error"}

    domain = get_domain(domain_key)
    if domain is None:
        return {"error": f"Unknown domain: {domain_key}", "extraction_status": "error"}

    claim_doc = next(
        (d for d in state["documents"] if d["doc_type"] == domain_key),
        None,
    )
    if claim_doc is None:
        return {"error": f"No {domain_key} document found in package", "extraction_status": "error"}

    try:
        result = extract(claim_doc["path"], domain.spec)
    except Exception as exc:
        return {"error": str(exc), "extraction_status": "error"}

    return {
        "extraction_data": result.data,
        "extraction_fields": [f.model_dump() for f in result.fields],
        "extraction_status": result.status,
        "extraction_overall_confidence": result.overall_confidence,
    }
