from pydantic import BaseModel


class SettingsResponse(BaseModel):
    confidence_threshold: float
    escalation_threshold: float
    enabled_domains: list[str]
    doc_intel_provider: str
    doc_intel_model: str
    ocr_provider: str
    ocr_fallback_providers: list[str]
    qdrant_url: str
    qdrant_collection: str
    langfuse_enabled: bool
    anthropic_api_key_configured: bool


class LLMCredentialsRequest(BaseModel):
    provider: str
    api_key: str | None = None
    model: str | None = None


class LLMCredentialsResponse(BaseModel):
    provider: str | None
    model: str | None
    key_set: bool
    key_last4: str | None
    providers: list[str]
    active_service: str
    active_model: str
    using_override: bool


class StatusResponse(BaseModel):
    status: str
