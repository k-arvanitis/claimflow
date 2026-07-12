from pydantic import BaseModel

from claimflow.schemas.enums import DocumentType


class DocumentSummary(BaseModel):
    document_id: str
    path: str
    doc_type: DocumentType
    has_text_layer: bool
    scan_quality: float | None
    classification_reason: str | None
    manually_overridden: bool


class DocumentReclassifyRequest(BaseModel):
    doc_type: DocumentType
    reviewer: str = "reviewer"


class DocumentReclassifyResponse(BaseModel):
    document_id: str
    doc_type: DocumentType
    classification_reason: str | None
    manually_overridden: bool
