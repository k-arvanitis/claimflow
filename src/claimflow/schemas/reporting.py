from datetime import datetime
from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import DecisionType, PackageStatus
from claimflow.schemas.review_write import ValidationFailureItem


class PolicyEvidenceItem(BaseModel):
    question: str
    answer: str
    citations: list[Any]


class AuditEventItem(BaseModel):
    actor: str
    action: str
    timestamp: datetime
    detail: dict[str, Any] | None


class ExtractionFieldExport(BaseModel):
    name: str
    value: Any | None
    confidence: float
    grounded: bool
    valid: bool
    field_status: str


class PolicyAnswerExport(BaseModel):
    question: str
    answer: str
    citations: list[Any]


class ExportResponse(BaseModel):
    package_id: str
    status: PackageStatus
    decision: DecisionType | None
    domain: str | None
    extraction_fields: list[ExtractionFieldExport]
    validation_failures: list[ValidationFailureItem]
    policy_answers: list[PolicyAnswerExport]
