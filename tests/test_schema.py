def test_settings_import():
    from claimflow.config import settings
    assert settings.llm_model == "claude-sonnet-4-6"
    assert settings.confidence_threshold == 0.75
