import os

# Propagate claimflow settings to doc-intel before its config.py is imported.
# doc-intel reads these env vars at import time; setdefault would be overridden
# by doc-intel's own load_dotenv() only for keys not yet in os.environ, so we
# use explicit assignment so claimflow's pydantic-settings (which reads .env)
# always wins.
from claimflow.config import settings  # noqa: E402 (must precede doc-intel import)

os.environ["DOC_INTEL_PROVIDER"] = settings.doc_intel_provider
os.environ["DOC_INTEL_MODEL"] = settings.doc_intel_model
if settings.doc_intel_llm_base_url:
    os.environ["DOC_INTEL_LLM_BASE_URL"] = settings.doc_intel_llm_base_url

from doc_intel.extract import extract  # noqa: E402

from claimflow.schemas.cms1500 import CMS1500_SPEC
from claimflow.state import ClaimState


def extract_node(state: ClaimState) -> dict:
    claim_doc = next(
        (d for d in state["documents"] if d["doc_type"] == "cms1500"),
        None,
    )
    if claim_doc is None:
        return {"error": "No CMS-1500 form found in package", "extraction_status": "error"}

    try:
        result = extract(claim_doc["path"], CMS1500_SPEC)
    except Exception as exc:
        return {"error": str(exc), "extraction_status": "error"}

    return {
        "extraction_data": result.data,
        "extraction_fields": [f.model_dump() for f in result.fields],
        "extraction_status": result.status,
        "extraction_overall_confidence": result.overall_confidence,
    }
