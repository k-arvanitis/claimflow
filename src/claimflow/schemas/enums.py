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
    """Every value the classifier can persist and return through the API.

    This includes deep-extraction domains and classification-only supporting
    document types. Keep it in sync with both `doc_type=` and
    `supporting_types=` registrations in `src/claimflow/domains/*.py`.
    """

    CMS1500 = "cms1500"
    EOB = "eob"
    MEDICARE_SUMMARY_NOTICE = "medicare_summary_notice"
    XACTIMATE = "xactimate"
    DECLARATIONS_PAGE = "declarations_page"
    LOAN = "loan"
    SBA_FORM_413 = "sba_form_413"
    SBA_FORM_2202 = "sba_form_2202"
    MEDICAL_BILL = "medical_bill"
    INSURANCE_POLICY = "insurance_policy"
    DENIAL_LETTER = "denial_letter"
    CLINICAL_NOTE = "clinical_note"
    LAB_REPORT = "lab_report"
    DISCHARGE_SUMMARY = "discharge_summary"
    REFERRAL_LETTER = "referral_letter"
    PRIOR_AUTHORIZATION_LETTER = "prior_authorization_letter"
    ELIGIBILITY_BENEFITS_VERIFICATION = "eligibility_benefits_verification"
    UB04_CMS1450 = "ub04_cms1450"
    LOSS_REPORT = "loss_report"
    CONTRACTOR_INVOICE = "contractor_invoice"
    ADJUSTER_NOTES = "adjuster_notes"
    ROOF_INSPECTION_REPORT = "roof_inspection_report"
    DAMAGE_PHOTO = "damage_photo"
    MATERIAL_RECEIPT = "material_receipt"
    FIRE_REPORT = "fire_report"
    POLICE_REPORT = "police_report"
    TAX_RETURN = "tax_return"
    BANK_STATEMENT = "bank_statement"
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    ID_DOCUMENT = "id_document"
    SUPPORTING_EXHIBIT = "supporting_exhibit"
    PROFIT_LOSS_STATEMENT = "profit_loss_statement"
    DEBT_SCHEDULE = "debt_schedule"
    BUSINESS_LICENSE = "business_license"
    ARTICLES_OF_INCORPORATION = "articles_of_incorporation"
    PAYROLL_REPORT = "payroll_report"
    W2_1099_PAYSTUB = "w2_1099_paystub"
    UNKNOWN = "unknown"
