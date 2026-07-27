from pydantic import BaseModel


class DomainPackSummary(BaseModel):
    key: str
    display_name: str
    document_types: list[str]


class DomainPackDetail(BaseModel):
    key: str
    display_name: str
    document_types: list[str]
    required_fields: list[str]
    optional_fields: list[str]
    confidence_threshold: float
    escalation_threshold: float
    policy_collection: str | None
    retrieval_mode: str
    reviewer_guidance: str
