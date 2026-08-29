from types import SimpleNamespace
from unittest.mock import patch

from jhenkan_app.converter import preserve_outer_whitespace
from jhenkan_app.converter import JapaneseConverter


def test_preserves_outer_whitespace():
    assert preserve_outer_whitespace("  watashi desu\n", "私はです") == "  私はです\n"


def test_does_not_duplicate_whitespace_from_result():
    assert preserve_outer_whitespace("hello", "  こんにちは  ") == "こんにちは"


def test_openai_uses_responses_api():
    with patch("jhenkan_app.converter.OpenAI") as openai:
        client = openai.return_value
        client.responses.create.return_value = SimpleNamespace(output_text="日本語")
        converter = JapaneseConverter("secret", "gpt-5.6-luna", provider="openai")

        assert converter.convert("nihongo") == "日本語"
        client.responses.create.assert_called_once()
        client.chat.completions.create.assert_not_called()


def test_gemini_uses_openai_compatible_chat_api():
    with patch("jhenkan_app.converter.OpenAI") as openai:
        client = openai.return_value
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="日本語"))]
        )
        converter = JapaneseConverter(
            "secret", "gemini-3.6-flash", provider="gemini"
        )

        assert converter.convert("nihongo") == "日本語"
        assert "generativelanguage.googleapis.com" in openai.call_args.kwargs["base_url"]
        call = client.chat.completions.create.call_args.kwargs
        assert call["model"] == "gemini-3.6-flash"
        assert call["reasoning_effort"] == "low"
        client.responses.create.assert_not_called()
