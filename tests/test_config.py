from jhenkan_app.config import Settings


def test_default_provider_is_gemini_36():
    settings = Settings()
    assert settings.provider == "gemini"
    assert settings.model == "gemini-3.6-flash"
    assert settings.diagnostic_text_logging is False


def test_model_tracks_provider():
    settings = Settings(provider="openai")
    assert settings.model == "gpt-5.6-luna"
