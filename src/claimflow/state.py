from typing import Literal, NotRequired, TypedDict


class IngestedDoc(TypedDict):
    path: str
    doc_type: str  # domain form key (e.g. "cms1500"), a supporting subtype (e.g. "medical_bill"), or "unknown"
    has_text_layer: bool
    scan_quality: (
        float | None
    )  # set only when OCR fallback ran on page 1; density heuristic, not real OCR confidence
    classification_reason: (
        str | None
    )  # why this doc_type was assigned; None for "unknown" or manual override not yet set


class ValidationFailure(TypedDict):
    field: str
    rule: str
    reason: str
    severity: Literal["error", "warning"]
    policy_required: bool
    # Authoritative comparison values for rules that check one number/value against
    # another (arithmetic, amount_consistency, acv_check, ...) — lets the UI show
    # "computed X vs reported Y" without re-deriving it from field text client-side.
    # Absent for rules with no meaningful comparison (e.g. a bad lookup code).
    machine_value: NotRequired[str | None]
    expected_value: NotRequired[str | None]


class PolicyAnswer(TypedDict):
    question: str
    answer: str
    citations: list[str]  # "source: page N" strings
    field: str | None  # which validation failure's field this answer supports
    rule: str | None  # which validation failure's rule this answer supports
    # "found": at least one relevant policy chunk was retrieved and synthesized.
    # "not_found": the corpus was searched but nothing relevant came back — distinct
    # from a failure that never triggers a policy lookup at all (policy_required=False),
    # which never produces a PolicyAnswer in the first place.
    status: Literal["found", "not_found"]


class ClaimState(TypedDict):
    # Input
    package_dir: str  # path to folder containing PDFs
    domain: (
        str | None
    )  # authoritative doc_type driving schema/validators/policy — user-selected if given, else detected
    doc_type_overrides: dict[
        str, str
    ]  # filename -> forced doc_type, from a reviewer's classification override

    # Ingest output
    documents: list[IngestedDoc]
    ocr_log: list[str]
    detected_domain: (
        str | None
    )  # what content classification alone would have picked; informational only
    domain_mismatch: (
        bool  # True when a user-selected domain disagrees with detected_domain
    )

    # Extract output — serialized ExtractionResult fields
    extraction_data: dict | None  # raw field values
    extraction_fields: list[dict] | None  # FieldConfidence list as dicts
    extraction_status: str | None  # "pass" | "review" | "error"
    extraction_overall_confidence: float | None

    # Extraction from every other document in the package with a registered
    # domain pack (e.g. an EOB alongside the primary CMS-1500). Read-only in
    # v1 — not merged into extraction_data, not editable in review, no
    # cross-document reconciliation against the primary extraction. Each
    # entry: {doc_type, filename, data, fields, status, overall_confidence,
    # error}. A per-document extraction failure lands as "error" on that
    # entry, not on extraction_status — one bad supporting doc doesn't fail
    # the whole run.
    secondary_extractions: list[dict] | None

    # Validate output
    validation_failures: list[ValidationFailure]

    # Retrieve output
    policy_answers: list[PolicyAnswer]

    # Review output
    decision: (
        Literal["ready_for_processing", "needs_review", "blocked_or_incomplete"] | None
    )
    review_reasons: list[str]

    # Error passthrough
    error: str | None
