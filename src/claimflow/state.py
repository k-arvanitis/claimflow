from typing import Literal, TypedDict


class IngestedDoc(TypedDict):
    path: str
    doc_type: str           # domain form key (e.g. "cms1500"), a supporting subtype (e.g. "medical_bill"), or "unknown"
    has_text_layer: bool
    scan_quality: float | None   # set only when OCR fallback ran on page 1; density heuristic, not real OCR confidence
    classification_reason: str | None   # why this doc_type was assigned; None for "unknown" or manual override not yet set


class ValidationFailure(TypedDict):
    field: str
    rule: str
    reason: str
    severity: Literal["error", "warning"]
    policy_required: bool


class PolicyAnswer(TypedDict):
    question: str
    answer: str
    citations: list[str]    # "source: page N" strings


class ClaimState(TypedDict):
    # Input
    package_dir: str        # path to folder containing PDFs
    domain: str | None      # detected doc_type, e.g. "cms1500" | "xactimate" | "loan"
    doc_type_overrides: dict[str, str]   # filename -> forced doc_type, from a reviewer's classification override

    # Ingest output
    documents: list[IngestedDoc]
    ocr_log: list[str]

    # Extract output — serialized ExtractionResult fields
    extraction_data: dict | None          # raw field values
    extraction_fields: list[dict] | None  # FieldConfidence list as dicts
    extraction_status: str | None         # "pass" | "review" | "error"
    extraction_overall_confidence: float | None

    # Validate output
    validation_failures: list[ValidationFailure]

    # Retrieve output
    policy_answers: list[PolicyAnswer]

    # Review output
    decision: Literal["ready_for_processing", "needs_review", "blocked_or_incomplete"] | None
    review_reasons: list[str]

    # Error passthrough
    error: str | None
