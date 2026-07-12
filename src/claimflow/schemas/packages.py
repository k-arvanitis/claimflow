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


class PackageDetailResponse(BaseModel):
    package_id: str
    status: PackageStatus
    result: dict[str, Any] | None
    error: str | None


class PackageDeleteResponse(BaseModel):
    package_id: str
    status: str


class PackageStatusResponse(BaseModel):
    package_id: str
    status: PackageStatus
