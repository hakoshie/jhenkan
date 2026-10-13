import json

import pytest

import jhenkan_app.config as config
from jhenkan_app.config import Settings


def test_default_provider_is_chatgpt_luna():
    settings = Settings()
    assert settings.provider == "chatgpt"
    assert settings.model == "gpt-6-luna"
    assert settings.reasoning_effort == "none"
    assert settings.diagnostic_text_logging is False


def test_model_tracks_provider():
    settings = Settings(provider="openai")
    assert settings.model == "gpt-6-luna"


@pytest.mark.parametrize("field", ["openai_model", "model"])
def test_load_migrates_previous_luna(tmp_path, monkeypatch, field):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"provider": "openai", field: "gpt-5.6-luna"}), encoding="utf-8")
    monkeypatch.setattr(config, "config_path", lambda: path)
    assert Settings.load().model == "gpt-6-luna"


def test_load_preserves_custom_model_and_provider(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"provider": "gemini", "openai_model": "custom-model",
                                "gemini_model": "custom-gemini"}), encoding="utf-8")
    monkeypatch.setattr(config, "config_path", lambda: path)
    settings = Settings.load()
    assert settings.openai_model == "custom-model"
    assert settings.model == "custom-gemini"
