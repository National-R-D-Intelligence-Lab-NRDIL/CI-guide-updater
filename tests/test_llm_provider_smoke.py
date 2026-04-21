import os

import pytest

import updater

SMOKE_GUIDE = (
    "# Program Snapshot\n\n"
    "## Eligibility\n"
    "- Public institutions only.\n\n"
    "## Deadline\n"
    "- Submit by June 1, 2026.\n"
)
SMOKE_DIFF = (
    "### Added/Modified Text\n\n"
    "+ ## Deadline\n"
    "+ - Submit by June 15, 2026.\n\n"
    "### Removed Text\n\n"
    "- - Submit by June 1, 2026.\n"
)
EXPECTED_HEADINGS = ("# Program Snapshot", "## Eligibility", "## Deadline")


def _assert_common_smoke_expectations(result: str) -> None:
    assert isinstance(result, str)
    assert result.strip(), "LLM result should not be empty"
    assert any(
        heading in result for heading in EXPECTED_HEADINGS
    ), "LLM response should preserve at least one guide heading"


@pytest.mark.smoke
def test_gemini_smoke() -> None:
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()

    if not api_key:
        pytest.skip("Skipping Gemini smoke: LLM_API_KEY is not set.")
    if "generativelanguage.googleapis.com" not in base_url:
        pytest.skip(
            "Skipping Gemini smoke: set LLM_BASE_URL to Gemini's OpenAI-compatible endpoint."
        )
    if model != "gemini-2.5-flash":
        pytest.skip(
            "Skipping Gemini smoke: set LLM_MODEL=gemini-2.5-flash."
        )

    result = updater.update_guide(SMOKE_GUIDE, SMOKE_DIFF)
    _assert_common_smoke_expectations(result)


@pytest.mark.smoke
def test_openai_or_anthropic_smoke() -> None:
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    known_openai = base_url.rstrip("/") == "https://api.openai.com/v1"
    uses_anthropic_bridge = "anthropic" in base_url.lower()

    if not api_key:
        pytest.skip("Skipping OpenAI/Anthropic smoke: LLM_API_KEY is not set.")
    if not (known_openai or uses_anthropic_bridge):
        pytest.skip(
            "Skipping OpenAI/Anthropic smoke: set LLM_BASE_URL to OpenAI v1 "
            "or Anthropic's OpenAI-compatible bridge endpoint."
        )
    if known_openai and model != "gpt-4o-mini":
        pytest.skip(
            "Skipping OpenAI smoke: set LLM_MODEL=gpt-4o-mini when using https://api.openai.com/v1."
        )

    result = updater.update_guide(SMOKE_GUIDE, SMOKE_DIFF)
    _assert_common_smoke_expectations(result)
