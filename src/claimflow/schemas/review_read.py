from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import PackageStatus


class FieldEvidenceResponse(BaseModel):
    field_id: int
    name: str
    value: Any | None
    confidence: float
    document_id: str
    filename: str
    page: int | None
    quote: str | None
    bbox: list[float] | None
    coordinate_system: str = "pdf_points"
    block_type: str | None
    evidence_unavailable: bool


class ReviewFieldSummary(BaseModel):
    field_id: int
    name: str
    value: Any | None
    confidence: float
    field_status: str
    parent_field: str | None
    reviewer_action: str | None = None
    corrected_value: Any | None = None
    reviewer: str | None = None
    reviewer_note: str | None = None


class ReviewValidationFailure(BaseModel):
    field: str
    rule: str
    reason: str
    severity: str
    policy_required: bool
    machine_value: str | None = None
    expected_value: str | None = None


class PackageReviewResponse(BaseModel):
    package_id: str
    status: PackageStatus
    fields: list[ReviewFieldSummary]
    validation_failures: list[ReviewValidationFailure]
