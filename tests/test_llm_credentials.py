"""Tests for src/claimflow/llm_credentials.py."""

import pytest

import claimflow.llm_credentials as llm_credentials


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Point the credentials store at a scratch file, and always end the test with
    no override active — _apply() mutates doc_intel.config module globals as a
    real side effect, which would otherwise leak into unrelated tests."""
    monkeypatch.setattr(llm_credentials, "_PATH", tmp_path / "llm_credentials.json")
    yield
    llm_credentials.clear_credentials()


def test_set_then_get_masked_round_trips_provider_and_model():
    llm_credentials.set_credentials(
        "groq", "sk-real-secret-key", "llama-3.3-70b-versatile"
    )
    masked = llm_credentials.get_masked()
    assert masked["provider"] == "groq"
    assert masked["model"] == "llama-3.3-70b-versatile"
    assert masked["key_set"] is True


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        llm_credentials.set_credentials("anthropic", "sk-key", None)


def test_clear_credentials_reverts_to_unset():
    llm_credentials.set_credentials("openai", "sk-key", None)
    llm_credentials.clear_credentials()
    masked = llm_credentials.get_masked()
    assert masked["key_set"] is False
    assert masked["provider"] is None


def test_key_last4_only_never_the_full_key():
    llm_credentials.set_credentials("openrouter", "sk-abcdefgh1234", None)
    masked = llm_credentials.get_masked()
    assert masked["key_last4"] == "1234"
    assert "sk-abcdefgh1234" not in str(masked)


def test_no_credentials_set_reports_unset():
    masked = llm_credentials.get_masked()
    assert masked == {
        "provider": None,
        "model": None,
        "key_set": False,
        "key_last4": None,
    }


def test_blank_api_key_on_resave_keeps_the_real_key():
    """The GET endpoint only ever returns a mask, so the settings form round-trips
    blank for "unchanged" — saving with a blank key must not wipe the working key."""
    llm_credentials.set_credentials(
        "groq", "sk-original-key", "llama-3.3-70b-versatile"
    )
    llm_credentials.set_credentials("groq", None, "llama-3.3-70b-versatile")
    masked = llm_credentials.get_masked()
    assert masked["key_last4"] == "-key"


def test_resolve_override_falls_back_to_provider_default_model():
    llm_credentials.set_credentials("groq", "sk-key", None)
    base_url, api_key, model = llm_credentials.resolve_override()
    assert base_url == "https://api.groq.com/openai/v1"
    assert api_key == "sk-key"
    assert model == "llama-3.3-70b-versatile"


def test_resolve_override_none_when_no_key_set():
    assert llm_credentials.resolve_override() is None


def test_active_model_identifies_openrouter_behind_openai_adapter():
    active = llm_credentials.get_active(
        "openai", "qwen/qwen3-32b", "https://openrouter.ai/api/v1"
    )
    assert active == {
        "active_service": "openrouter",
        "active_model": "qwen/qwen3-32b",
        "using_override": False,
    }


def test_active_model_resolves_override_provider_default():
    llm_credentials.set_credentials("groq", "sk-key", None)
    active = llm_credentials.get_active("anthropic", "claude-sonnet-4-6", "")
    assert active == {
        "active_service": "groq",
        "active_model": "llama-3.3-70b-versatile",
        "using_override": True,
    }


def test_set_credentials_pushes_override_into_doc_intel_config():
    from doc_intel import config as doc_intel_config

    llm_credentials.set_credentials("openai", "sk-key", "gpt-4o-mini")
    assert doc_intel_config.PROVIDER == "openai"
    assert doc_intel_config.MODEL == "gpt-4o-mini"
    assert doc_intel_config.OPENAI_API_KEY == "sk-key"
    assert doc_intel_config.LLM_BASE_URL == "https://api.openai.com/v1"


def test_clear_credentials_restores_doc_intel_config_originals():
    from doc_intel import config as doc_intel_config

    original_provider = doc_intel_config.PROVIDER
    original_model = doc_intel_config.MODEL

    llm_credentials.set_credentials("openai", "sk-key", "gpt-4o-mini")
    llm_credentials.clear_credentials()

    assert doc_intel_config.PROVIDER == original_provider
    assert doc_intel_config.MODEL == original_model
