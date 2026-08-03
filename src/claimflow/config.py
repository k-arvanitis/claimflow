from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (extraction + retrieval synthesis)
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    llm_model: str = "claude-sonnet-4-6"

    # doc-intel passthrough
    doc_intel_provider: str = Field(
        default="anthropic", validation_alias="CLAIMFLOW_DOC_INTEL_PROVIDER"
    )
    doc_intel_model: str = Field(
        default="claude-sonnet-4-6", validation_alias="CLAIMFLOW_DOC_INTEL_MODEL"
    )
    doc_intel_llm_base_url: str = Field(
        default="", validation_alias="CLAIMFLOW_DOC_INTEL_LLM_BASE_URL"
    )  # empty = doc-intel default (official API)
    doc_intel_max_tokens: int = Field(
        default=8192, validation_alias="CLAIMFLOW_DOC_INTEL_MAX_TOKENS"
    )
    doc_intel_paddleocr_vl_server_url: str = Field(
        default="", validation_alias="CLAIMFLOW_DOC_INTEL_PADDLEOCR_VL_SERVER_URL"
    )  # empty = doc-intel falls back to its configured OCR_FALLBACK_PROVIDERS (tesseract)

    # Qdrant
    qdrant_url: str = "http://localhost:6339"
    qdrant_collection: str = "claimflow_policies"

    # Thresholds
    confidence_threshold: float = 0.75
    escalation_threshold: float = 0.50  # below this → escalate, not just flag

    # Langfuse (optional)
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Persistence (SQLite job/audit store + uploaded-file staging dir).
    # NOT encrypted at rest — see TODO.md.
    db_path: str = "data/claimflow.db"
    storage_dir: str = "data/uploads"
    max_upload_size_bytes: int = 20_000_000  # 20MB per file
    max_files_per_package: int = 30

    # CORS: the Next.js frontend (frontend/) runs on a different origin/port in dev.
    # Comma-separated list of allowed origins.
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:3001"


settings = Settings()
