from unittest.mock import patch

import pytest

from src.utils import llm_client


@patch("src.utils.llm_client.OpenAI")
def test_get_llm_client_uses_default_base_url_when_unset(mock_openai, monkeypatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "preferred-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    llm_client.get_llm_client()

    mock_openai.assert_called_once_with(
        api_key="preferred-key",
        base_url=llm_client.DEFAULT_BASE_URL,
    )


@patch("src.utils.llm_client.OpenAI")
def test_get_llm_client_prefers_llm_api_key_over_gemini_key(mock_openai, monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "llm-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    llm_client.get_llm_client()

    mock_openai.assert_called_once_with(
        api_key="llm-key",
        base_url=llm_client.DEFAULT_BASE_URL,
    )


@patch("src.utils.llm_client.OpenAI")
def test_get_llm_client_uses_gemini_key_when_llm_key_missing(mock_openai, monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    llm_client.get_llm_client()

    mock_openai.assert_called_once_with(
        api_key="gemini-key",
        base_url=llm_client.DEFAULT_BASE_URL,
    )


def test_get_llm_client_raises_when_no_api_key(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(EnvironmentError, match="Set LLM_API_KEY .* GEMINI_API_KEY"):
        llm_client.get_llm_client()


@patch("src.utils.llm_client.OpenAI")
def test_get_llm_client_honors_base_url_override(mock_openai, monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "preferred-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1/")

    llm_client.get_llm_client()

    mock_openai.assert_called_once_with(
        api_key="preferred-key",
        base_url="https://example.test/v1/",
    )


def test_get_default_model_uses_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert llm_client.get_default_model() == llm_client.DEFAULT_MODEL


def test_get_default_model_honors_override(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "my-model")
    assert llm_client.get_default_model() == "my-model"

