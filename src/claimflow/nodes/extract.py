from doc_intel.extract import extract

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
