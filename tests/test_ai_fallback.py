"""
Tests for AI multi-provider fallback and prompt generation logic.
"""

import pytest
import os
from unittest.mock import patch, MagicMock
from src.ai_text import (
    generate_caption,
    build_system_prompt,
    build_user_prompt,
    call_gemini,
    call_groq,
    call_openrouter,
)


@pytest.fixture
def sample_config():
    return {
        "brand": {
            "name": "TestPage",
            "niche": "Technology",
            "target_audience": "Developers",
            "language": "mixed",
            "tone": "engaging",
            "emoji": True,
            "hashtags": {"enabled": True, "count": 3},
            "max_caption_length": 500,
            "custom_system_prompt": "Always be inspiring.",
        },
        "ai": {
            "text_providers": ["gemini", "groq", "openrouter"],
            "models": {
                "gemini": "gemini-1.5-flash",
                "groq": "llama-3.3-70b-versatile",
                "openrouter": "meta-llama/llama-3.3-70b-instruct",
            },
            "vision_enabled_for_drive": False,
        },
    }


def test_build_system_prompt(sample_config):
    prompt = build_system_prompt(sample_config)
    assert "TestPage" in prompt
    assert "Technology" in prompt
    assert "Always be inspiring." in prompt


def test_build_user_prompt(sample_config):
    prompt = build_user_prompt("Clean Architecture in Python", sample_config, recent_captions=["Old caption 1"])
    assert "Clean Architecture in Python" in prompt
    assert "exactly 3 relevant hashtags" in prompt
    assert "Old caption 1" in prompt


@patch.dict(os.environ, {
    "GEMINI_API_KEY": "dummy_gemini_key",
    "GROQ_API_KEY": "dummy_groq_key",
    "OPENROUTER_API_KEY": "dummy_openrouter_key",
})
@patch("src.ai_text.call_gemini")
@patch("src.ai_text.call_groq")
def test_fallback_when_first_provider_fails(mock_groq, mock_gemini, sample_config):
    # Gemini fails with 429 rate limit
    mock_gemini.side_effect = RuntimeError("Gemini API returned status 429: Resource Exhausted")
    # Groq succeeds
    mock_groq.return_value = "Awesome Groq generated caption with #Python #Tech"

    caption, provider = generate_caption("AI in 2026", sample_config)

    assert provider == "groq"
    assert "Awesome Groq" in caption
    assert mock_gemini.called
    assert mock_groq.called


@patch.dict(os.environ, {
    "GEMINI_API_KEY": "dummy_gemini_key",
    "GROQ_API_KEY": "dummy_groq_key",
    "OPENROUTER_API_KEY": "dummy_openrouter_key",
})
@patch("src.ai_text.call_gemini")
@patch("src.ai_text.call_groq")
@patch("src.ai_text.call_openrouter")
def test_all_providers_fail_raises_runtime_error(mock_openrouter, mock_groq, mock_gemini, sample_config):
    mock_gemini.side_effect = RuntimeError("Gemini rate limit")
    mock_groq.side_effect = RuntimeError("Groq server error 500")
    mock_openrouter.side_effect = RuntimeError("OpenRouter payment required")

    with pytest.raises(RuntimeError) as exc_info:
        generate_caption("Topic That Fails", sample_config)

    assert "All AI text generation providers failed" in str(exc_info.value)
