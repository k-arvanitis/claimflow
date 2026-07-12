from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import PackageStatus


class FieldEvidenceResponse(BaseModel):
    field_id: int
    name: str
    value: Any | None
    confidence: float
    evidence: dict[str, Any] | None


class ReviewFieldSummary(BaseModel):
    field_id: int
    name: str
    value: Any | None
    confidence: float
    field_status: str


class ReviewValidationFailure(BaseModel):
    field: str
    rule: str
    reason: str


class PackageReviewResponse(BaseModel):
    package_id: str
    status: PackageStatus
    fields: list[ReviewFieldSummary]
    validation_failures: list[ReviewValidationFailure]
