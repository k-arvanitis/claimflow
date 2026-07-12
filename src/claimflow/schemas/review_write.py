from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import DecisionType, ReviewActionType


class FieldReviewRequest(BaseModel):
    action: ReviewActionType
    corrected_value: Any | None = None
    validation_after: list[str] | None = None
    reviewer: str = "reviewer"
    note: str | None = None


class FieldReviewResponse(BaseModel):
    field_id: int
    action: ReviewActionType
    reviewer: str
    corrected_value: Any | None


class ValidationRerunRequest(BaseModel):
    corrected_fields: dict[str, Any] = {}


class ValidationFailureItem(BaseModel):
    field: str
    rule: str
    reason: str


class ValidationRerunResponse(BaseModel):
    validation_failures: list[ValidationFailureItem]


class DecisionRequest(BaseModel):
    decision: DecisionType
    review_reasons: list[str] = []


class DecisionResponse(BaseModel):
    package_id: str
    decision: DecisionType
