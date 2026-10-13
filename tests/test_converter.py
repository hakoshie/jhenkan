from types import SimpleNamespace
import json
import pytest
from unittest.mock import patch

from jhenkan_app.converter import preserve_outer_whitespace
from jhenkan_app.converter import JapaneseConverter
from jhenkan_app.converter import INSTRUCTIONS


def test_identical_alternative_does_not_get_pasted():
    with patch("jhenkan_app.converter.OpenAI") as openai:
        openai.return_value.responses.create.return_value = SimpleNamespace(output_text="個室")
        with pytest.raises(RuntimeError, match="別候補が見つかりません"):
            JapaneseConverter("secret", "gpt-6-luna").convert("kositu", previous="個室")


def test_alternative_sends_original_and_previous_without_changing_plain_requests():
    with patch("jhenkan_app.converter.OpenAI") as openai:
        client = openai.return_value
        client.responses.create.return_value = SimpleNamespace(output_text="固執")
        converter = JapaneseConverter("secret", "gpt-6-luna")
        assert converter.convert("kositu", previous="個室") == "固執"
        call = client.responses.create.call_args.kwargs
        assert call["instructions"].startswith(INSTRUCTIONS + "\n\n")
        assert json.loads(call["input"]) == {"source": "kositu", "previous": "個室"}
        converter.convert("nihongo")
        assert client.responses.create.call_args.kwargs["input"] == "nihongo"
        assert client.responses.create.call_args.kwargs["instructions"] == INSTRUCTIONS


def test_preserves_outer_whitespace():
    assert preserve_outer_whitespace("  watashi desu\n", "私はです") == "  私はです\n"


def test_does_not_duplicate_whitespace_from_result():
    assert preserve_outer_whitespace("hello", "  こんにちは  ") == "こんにちは"


def test_openai_uses_responses_api():
    with patch("jhenkan_app.converter.OpenAI") as openai:
        client = openai.return_value
        client.responses.create.return_value = SimpleNamespace(output_text="日本語")
        converter = JapaneseConverter("secret", "gpt-6-luna", provider="openai")

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


def test_chatgpt_streams_with_supported_fields_and_applies_sol_low():
    events = [SimpleNamespace(type="response.output_text.delta", delta="日本"),
              SimpleNamespace(type="response.output_text.delta", delta="語"),
              SimpleNamespace(type="response.completed")]
    with patch("jhenkan_app.converter.OpenAI") as openai:
        request = openai.return_value.responses.create
        request.return_value.__enter__.return_value = iter(events)
        converter = JapaneseConverter("oauth-secret", "gpt-6.1-sol", provider="chatgpt")
        assert converter.convert("  nihongo\n") == "  日本語\n"
        kwargs = request.call_args.kwargs
        assert kwargs["stream"] is True and kwargs["store"] is False
        assert kwargs["input"] == [{"role": "user", "content": "  nihongo\n"}]
        assert kwargs["reasoning"] == {"effort": "low"}
        assert "max_output_tokens" not in kwargs


@pytest.mark.parametrize("ending", ["response.failed", "response.incomplete", "error", None])
def test_chatgpt_rejects_partial_results(ending):
    events = [SimpleNamespace(type="response.output_text.delta", delta="途中")]
    if ending:
        events.append(SimpleNamespace(type=ending))
    with patch("jhenkan_app.converter.OpenAI") as openai:
        openai.return_value.responses.create.return_value.__enter__.return_value = iter(events)
        with pytest.raises(RuntimeError):
            JapaneseConverter("oauth-secret", "gpt-6-luna", provider="chatgpt").convert("totyuu")
