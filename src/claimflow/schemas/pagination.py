from pydantic import BaseModel

from claimflow.schemas.packages import PackageSummary


class PaginatedPackagesResponse(BaseModel):
    items: list[PackageSummary]
    page: int
    page_size: int
    total: int
