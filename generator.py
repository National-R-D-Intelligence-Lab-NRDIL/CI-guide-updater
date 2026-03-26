"""Guide Generator module.

Scrapes all discovered source pages and asks Gemini to produce a
first-draft Sponsor Guide in markdown.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

import scraper

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """\
You are an expert Research Development assistant who writes Sponsor Guides \
for university faculty. A Sponsor Guide is a comprehensive reference document \
that faculty use when preparing grant proposals.

Given scraped text from multiple authoritative source pages, create a \
complete markdown Sponsor Guide. The guide MUST include these sections \
(skip a section only if the sources contain no relevant info):

1. Executive Summary
2. Program Overview
3. Key Dates (use a markdown table)
4. Eligibility
5. Award Size & Budget
6. How Proposals are Reviewed (review criteria, scoring)
7. Application Requirements (page limits, required forms, key personnel)
8. Tips for Successful Proposals
9. Resources (links to official pages)

Rules:
- Use ONLY facts from the provided source texts. Never hallucinate.
- Preserve exact dates, dollar amounts, and policy language.
- Use clear markdown: headings, bullet lists, tables, bold for emphasis.
- At the end, list every source URL under a "## Sources" heading.
"""


def generate_guide(
    sources: list[dict],
    program: str,
    model_name: str = DEFAULT_MODEL,
) -> str:
    """Scrape sources and generate a first-draft Sponsor Guide.

    Args:
        sources: List of dicts with ``name``, ``url``, ``sections``.
        program: Human-readable program name for the guide title.
        model_name: Gemini model to use.

    Returns:
        Markdown string of the generated guide.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set.")

    source_texts: list[str] = []
    for src in sources:
        name, url = src["name"], src["url"]
        print(f"  Scraping {name} ...")
        try:
            text = scraper.fetch_and_clean_text(url)
            source_texts.append(
                f"### Source: {name}\nURL: {url}\n\n{text}"
            )
        except Exception as exc:
            print(f"  ⚠  {name}: failed — {exc}")

    if not source_texts:
        raise RuntimeError("No sources could be scraped.")

    combined = "\n\n---\n\n".join(source_texts)

    user_prompt = (
        f'Create a Sponsor Guide for the "{program}" grant program.\n\n'
        f"Below are the scraped source pages:\n\n{combined}"
    )

    client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)

    print(f"\n  Generating guide with {model_name} ...")
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    return response.choices[0].message.content
