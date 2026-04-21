"""Factory helpers for OpenAI-compatible LLM client configuration."""

from __future__ import annotations

from openai import OpenAI

from src.utils.secrets import get_secret

DEFAULT_PROVIDER = "gemini"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.5-flash"


def get_llm_client() -> OpenAI:
    """Build an OpenAI client from environment-backed settings.

    Uses ``LLM_API_KEY`` first, then falls back to ``GEMINI_API_KEY`` for
    backward compatibility.
    """
    base_url = get_secret("LLM_BASE_URL") or DEFAULT_BASE_URL
    api_key = get_secret("LLM_API_KEY") or get_secret("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Missing API key for OpenAI-compatible LLM client. Set LLM_API_KEY "
            "(preferred) or GEMINI_API_KEY (backward compatibility)."
        )

    return OpenAI(api_key=api_key, base_url=base_url)


def get_default_model() -> str:
    """Return ``LLM_MODEL`` from environment or the built-in default."""
    return get_secret("LLM_MODEL") or DEFAULT_MODEL

