from typing import Literal, TypedDict


class IngestedDoc(TypedDict):
    path: str
    doc_type: str           # "cms1500" | "supporting" | "unknown"
    has_text_layer: bool


class ValidationFailure(TypedDict):
    field: str
    rule: str
    reason: str


class PolicyAnswer(TypedDict):
    question: str
    answer: str
    citations: list[str]    # "source: page N" strings


class ClaimState(TypedDict):
    # Input
    package_dir: str        # path to folder containing PDFs

    # Ingest output
    documents: list[IngestedDoc]

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
    decision: Literal["approved", "flagged", "escalated"] | None
    review_reasons: list[str]

    # Error passthrough
    error: str | None
