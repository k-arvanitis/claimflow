from datetime import datetime
from typing import Any

from pydantic import BaseModel

from claimflow.schemas.enums import PackageStatus


class PackageCreateResponse(BaseModel):
    package_id: str
    status: PackageStatus


class PackageSummary(BaseModel):
    package_id: str
    status: PackageStatus
    created_at: datetime
    updated_at: datetime
    domain: str | None = None
    decision: str | None = None
    overall_confidence: float | None = None
    document_count: int
    validation_failure_count: int


class PackageDetailResponse(BaseModel):
    package_id: str
    status: PackageStatus
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    domain: str | None = None
    decision: str | None = None
    review_reasons: list[str] = []
    overall_confidence: float | None = None
    document_count: int = 0
    validation_failure_count: int = 0


class PackageDeleteResponse(BaseModel):
    package_id: str
    status: str


class PackageStatusResponse(BaseModel):
    package_id: str
    status: PackageStatus
