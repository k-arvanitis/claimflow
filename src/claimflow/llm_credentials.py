"""JSON-file-backed store for an admin-provided LLM override (bring-your-own-key).

Lets the operator pick Groq, OpenRouter, or OpenAI (plus a model) at runtime instead
of the env-configured Anthropic extraction/retrieval LLM — no .env edit, no restart.
Doc-intel reads its provider/model/key/base_url from plain module globals at import
time with no reconfiguration hook, so applying an override means mutating those
globals directly; clearing restores the values captured on first use.

ponytail: plaintext on disk, gitignored — same trust model as .env. No per-user
keys, no rotation, single global override (not per-package).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

PROVIDERS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
    },
    "openai": {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini"},
}


def infer_service(provider: str, base_url: str) -> str:
    """Return the actual service, not the protocol adapter used to call it."""
    normalized_url = base_url.rstrip("/").lower()
    for service, config in PROVIDERS.items():
        if normalized_url and normalized_url == config["base_url"].rstrip("/").lower():
            return service
    if "api.anthropic.com" in normalized_url:
        return "anthropic"
    if normalized_url and provider == "openai":
        return "custom"
    return provider


def get_active(
    default_provider: str, default_model: str, default_base_url: str
) -> dict:
    """Resolve the service and model that the next LLM call will actually use."""
    with _lock:
        record = _load()
    if record and record.get("api_key"):
        service = record["provider"]
        return {
            "active_service": service,
            "active_model": record.get("model") or PROVIDERS[service]["default_model"],
            "using_override": True,
        }
    return {
        "active_service": infer_service(default_provider, default_base_url),
        "active_model": default_model,
        "using_override": False,
    }


_lock = threading.Lock()
_PATH = Path("data/llm_credentials.json")


def _load() -> dict | None:
    if not _PATH.exists():
        return None
    return json.loads(_PATH.read_text()) or None


def _save(record: dict | None) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(record or {}, indent=2))


def get_masked() -> dict:
    """{provider, model, key_set, key_last4} for the settings UI — never the full key."""
    with _lock:
        record = _load()
    if not record or not record.get("api_key"):
        return {"provider": None, "model": None, "key_set": False, "key_last4": None}
    key = record["api_key"]
    return {
        "provider": record["provider"],
        "model": record.get("model") or "",
        "key_set": True,
        "key_last4": key[-4:] if len(key) >= 4 else "***",
    }


def set_credentials(provider: str, api_key: str | None, model: str | None) -> None:
    """A blank/omitted api_key keeps the existing stored key — the GET endpoint only
    ever returns a mask, so the settings form round-trips "unchanged" as blank, not
    the mask itself; treating blank as "clear" would wipe a working key on every save
    that doesn't retype it."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    with _lock:
        existing = _load() or {}
        key = api_key if api_key else existing.get("api_key", "")
        _save({"provider": provider, "api_key": key, "model": model or ""})
    _apply()


def clear_credentials() -> None:
    with _lock:
        _save(None)
    _apply()


def resolve_override() -> tuple[str, str, str] | None:
    """(base_url, api_key, model) if an override is active, else None."""
    with _lock:
        record = _load()
    if not record or not record.get("api_key"):
        return None
    cfg = PROVIDERS[record["provider"]]
    model = record.get("model") or cfg["default_model"]
    return cfg["base_url"], record["api_key"], model


_doc_intel_originals: dict[str, object] | None = None


def _apply() -> None:
    """Push the current override (or its absence) into doc-intel's config globals
    and drop claimflow's own cached retrieval-LLM client so both pick it up on the
    next call."""
    global _doc_intel_originals
    from doc_intel import config as doc_intel_config

    from claimflow.nodes import retrieve as retrieve_node

    if _doc_intel_originals is None:
        _doc_intel_originals = {
            "PROVIDER": doc_intel_config.PROVIDER,
            "MODEL": doc_intel_config.MODEL,
            "OPENAI_API_KEY": doc_intel_config.OPENAI_API_KEY,
            "LLM_BASE_URL": doc_intel_config.LLM_BASE_URL,
        }

    override = resolve_override()
    if override is None:
        for key, value in _doc_intel_originals.items():
            setattr(doc_intel_config, key, value)
    else:
        base_url, api_key, model = override
        doc_intel_config.PROVIDER = (
            "openai"  # groq/openrouter/openai are all OpenAI-compatible
        )
        doc_intel_config.MODEL = model
        doc_intel_config.OPENAI_API_KEY = api_key
        doc_intel_config.LLM_BASE_URL = base_url

    retrieve_node.reset_llm_client()
