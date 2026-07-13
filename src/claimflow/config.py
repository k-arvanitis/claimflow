from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (extraction + retrieval synthesis)
    anthropic_api_key: SecretStr = SecretStr("")
    llm_model: str = "claude-sonnet-4-6"

    # doc-intel passthrough
    doc_intel_provider: str = "anthropic"
    doc_intel_model: str = "claude-sonnet-4-6"
    doc_intel_llm_base_url: str = ""  # empty = doc-intel default (official API)

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


settings = Settings()
