from pydantic import BaseModel


class ValidationFailureCount(BaseModel):
    rule: str
    count: int


class DashboardSummaryResponse(BaseModel):
    total_packages: int
    processing: int
    awaiting_review: int
    approved: int
    flagged: int
    escalated: int
    processing_errors: int
    straight_through_rate: float
    top_validation_failures: list[ValidationFailureCount]
