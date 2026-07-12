from enum import Enum


class PackageStatus(str, Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    REVIEW_READY = "review_ready"
    COMPLETED = "completed"
    PROCESSING_ERROR = "processing_error"
    VALIDATION_ERROR = "validation_error"
    RETRIEVAL_ERROR = "retrieval_error"


class ExtractionRunStatus(str, Enum):
    PASS = "pass"
    REVIEW = "review"
    ERROR = "error"


class DecisionType(str, Enum):
    APPROVED = "approved"
    FLAGGED = "flagged"
    ESCALATED = "escalated"


class ReviewActionType(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
    ADD = "add"


class DocumentType(str, Enum):
    """Mirrors `doc_type=` registrations in src/claimflow/domains/*.py, plus the
    classifier's "unknown" fallback (nodes/ingest.py). Update this list when a
    domain module registers a new doc_type."""

    CMS1500 = "cms1500"
    EOB = "eob"
    MEDICARE_SUMMARY_NOTICE = "medicare_summary_notice"
    XACTIMATE = "xactimate"
    DECLARATIONS_PAGE = "declarations_page"
    LOAN = "loan"
    SBA_FORM_413 = "sba_form_413"
    SBA_FORM_2202 = "sba_form_2202"
    UNKNOWN = "unknown"
