"""LLM Updater module.

Takes the current markdown Sponsor Guide and a diff string produced by the
Diff Engine, then uses an LLM to rewrite only the affected sections while
preserving all original formatting.

Configured for Google Gemini via its OpenAI-compatible endpoint.  Set
``GEMINI_API_KEY`` in the environment (or a ``.env`` file) before use.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "You are an expert Research Development assistant. Your task is to update "
    "an existing markdown Sponsor Guide based on newly detected policy changes. "
    "You must seamlessly integrate the changes, retain all original markdown "
    "formatting, and strictly avoid hallucinating any rules, deadlines, or "
    "eligibility criteria not present in the diff.\n\n"
    "Return ONLY the updated markdown — no preamble, no commentary."
)


def _build_user_prompt(current_guide_md: str, diff_text: str) -> str:
    """Assemble the user-facing prompt that pairs the guide with its diff.

    Args:
        current_guide_md: Full markdown text of the existing Sponsor Guide.
        diff_text: Structured change summary produced by ``differ.extract_changes``.

    Returns:
        A single prompt string ready to send to the LLM.
    """
    return (
        "Below is the current Sponsor Guide followed by the detected changes. "
        "Please apply the changes to the guide and return the complete updated "
        "markdown.\n\n"
        "## Current Sponsor Guide\n\n"
        f"{current_guide_md}\n\n"
        "## Detected Changes\n\n"
        f"{diff_text}"
    )


def update_guide(
    current_guide_md: str,
    diff_text: str,
    model_name: str = DEFAULT_MODEL,
) -> str:
    """Send the guide and diff to an LLM and return the rewritten guide.

    Uses Google Gemini's OpenAI-compatible chat completions endpoint.

    Args:
        current_guide_md: Full markdown of the current Sponsor Guide.
        diff_text: Change summary from the Diff Engine.
        model_name: Model identifier (default ``gemini-2.0-flash``).

    Returns:
        The updated markdown text produced by the LLM.

    Raises:
        EnvironmentError: If ``GEMINI_API_KEY`` is not set.
        openai.APIConnectionError: On network-level failures.
        openai.APIStatusError: On non-2xx API responses (rate limits, auth, etc.).
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Add it to .env in the project root "
            f"({_PROJECT_ROOT / '.env'}) as GEMINI_API_KEY=... or export it in your shell."
        )

    client = OpenAI(
        api_key=api_key,
        base_url=GEMINI_BASE_URL,
    )

    user_prompt = _build_user_prompt(current_guide_md, diff_text)

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    return response.choices[0].message.content


def classify_sections(
    page_text: str,
    guide_md: str,
    model_name: str = DEFAULT_MODEL,
) -> list[str]:
    """Ask the LLM which guide sections a scraped page is relevant to.

    Extracts the heading titles from *guide_md*, sends them alongside a
    snippet of the page text, and returns the matched section names.

    Args:
        page_text: Cleaned text from a scraped web page.
        guide_md: Current guide markdown (headings are extracted automatically).
        model_name: Gemini model to use.

    Returns:
        List of section title strings (may be empty).
    """
    import re

    headings = re.findall(r"^#{1,3}\s+(.+)$", guide_md, re.MULTILINE)
    if not headings:
        return []

    heading_list = "\n".join(f"- {h.strip()}" for h in headings)
    snippet = page_text[:3000]

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []

    client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)

    prompt = (
        "Below is a list of section headings from a Sponsor Guide, "
        "followed by a snippet of text from a web page.\n\n"
        "## Guide Sections\n\n"
        f"{heading_list}\n\n"
        "## Web Page Snippet\n\n"
        f"{snippet}\n\n"
        "Which guide sections does this web page content relate to? "
        "Return ONLY a JSON array of matching section title strings. "
        "If none match, return an empty array []."
    )

    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )

    import json as _json

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        result = _json.loads(raw)
        if isinstance(result, list):
            return [s for s in result if isinstance(s, str)]
    except _json.JSONDecodeError:
        pass
    return []


if __name__ == "__main__":
    sample_guide = """\
# NIH R15 — Research Enhancement Award

## Key Dates

| Milestone        | Date         |
|------------------|--------------|
| Letter of Intent | Jan 15, 2025 |
| Application Due  | Feb 25, 2025 |

## Eligibility

- U.S. domestic institutions only.
- Undergraduate-focused institutions that have not received more than \
$6 million per year in NIH support.

## Budget

Up to **$300,000** in direct costs over the entire project period.
"""

    sample_diff = """\
### Added/Modified Text

  + Application Due  | March 5, 2025 |
  + - Applicants must include a Data Management and Sharing Plan.

### Removed Text

  - Application Due  | Feb 25, 2025 |
"""

    print("=" * 60)
    print("LLM UPDATER — Demo")
    print("=" * 60)
    print()

    try:
        updated = update_guide(sample_guide, sample_diff)
        print(updated)
    except EnvironmentError as exc:
        print(f"[CONFIG ERROR] {exc}")
    except APIConnectionError as exc:
        print(f"[CONNECTION ERROR] Could not reach the LLM endpoint: {exc}")
    except APIStatusError as exc:
        print(
            f"[API ERROR] {exc.status_code} from the LLM provider: {exc.message}"
        )
