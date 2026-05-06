"""Guide Generator module.

Scrapes all discovered source pages and asks Gemini to produce a
first-draft Sponsor Guide in markdown.
"""

import logging
import os
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

import scraper
from src.utils.llm_client import get_default_model, get_llm_client
from src.utils.sensitive_data import enforce_sensitive_data_policy
from src.utils.source_policy import assert_public_sources

DEFAULT_MAX_INPUT_CHARS = 200_000
MAX_INPUT_CHARS = int(
    os.getenv("LLM_MAX_INPUT_CHARS", str(DEFAULT_MAX_INPUT_CHARS))
)
MIN_SOURCE_INPUT_CHARS = 20_000

logger = logging.getLogger(__name__)

REQUIRED_GUIDE_SECTIONS = [
    "Executive Summary",
    "Program Overview",
    "Key Dates",
    "Eligibility",
    "Award Size & Budget",
    "How Proposals are Reviewed",
    "Application Requirements",
    "Tips for Successful Proposals",
    "Resources",
]

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
- Key Dates tables: use compact rows (header, separator, then data rows); never pad cells with spaces to fill width.
- At the end, list every source URL under a "## Sources" heading.
"""


def _best_effort_fetch_text(url: str) -> str:
    """Fetch readable page text directly when primary scraper fails."""
    response = requests.get(
        url,
        timeout=30,
        headers=getattr(scraper, "DEFAULT_REQUEST_HEADERS", {}),
    )
    response.raise_for_status()
    html = str(getattr(response, "text", "") or "")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _truncate_for_llm(text: str, max_chars: int, context: str) -> str:
    """Clamp text to an LLM-safe size and warn if truncated."""
    if len(text) <= max_chars:
        return text
    logger.warning(
        "Truncating %s from %d to %d chars before LLM call.",
        context,
        len(text),
        max_chars,
    )
    return text[:max_chars]


def _source_input_budget(source_count: int) -> int:
    """Return a per-source character budget so no source is starved."""
    if source_count <= 0:
        return MAX_INPUT_CHARS
    return max(MIN_SOURCE_INPUT_CHARS, MAX_INPUT_CHARS // source_count)


def _normalize_heading_text(heading: str) -> str:
    """Normalize markdown heading text for section-title matching."""
    text = heading.strip().strip("#").strip()
    text = re.sub(r"^\d+[\.\)]\s*", "", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _extract_markdown_headings(markdown: str) -> list[str]:
    """Extract ATX markdown heading texts."""
    heading_re = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
    return [m.group(1).strip() for m in heading_re.finditer(markdown)]


def find_missing_required_sections(markdown: str) -> list[str]:
    """Return required guide sections that are missing from markdown headings."""
    headings = _extract_markdown_headings(markdown)
    normalized_headings = [_normalize_heading_text(h) for h in headings]

    missing: list[str] = []
    for required in REQUIRED_GUIDE_SECTIONS:
        normalized_required = _normalize_heading_text(required)
        present = any(
            heading == normalized_required
            or heading.startswith(f"{normalized_required} ")
            for heading in normalized_headings
        )
        if not present:
            missing.append(required)
    return missing


def generate_guide(
    sources: list[dict],
    program: str,
    model_name: Optional[str] = None,
) -> str:
    """Scrape sources and generate a first-draft Sponsor Guide.

    Args:
        sources: List of dicts with ``name``, ``url``, ``sections``.
        program: Human-readable program name for the guide title.
        model_name: Gemini model to use.

    Returns:
        Markdown string of the generated guide.
    """
    client = get_llm_client()
    if model_name is None:
        model_name = get_default_model()
    assert_public_sources(sources, context="guide generation")

    scraped_sources: list[tuple[str, str, str, str]] = []
    scrape_failures: list[str] = []
    for src in sources:
        name = str(src.get("name", "")).strip()
        url = str(src.get("url", "")).strip()
        file_path = str(src.get("file_path", "")).strip()
        source_ref = url or file_path
        logger.info("event=scrape_start source=%s ref=%s", name, source_ref)
        try:
            payload = scraper.fetch_source_payload_from_source(src)
            if not isinstance(payload, dict):
                raise ValueError(f"Scraper returned invalid payload type: {type(payload).__name__}")
            text = payload.get("text", "")
            metadata = payload.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            source_method = str(metadata.get("extraction_method", "")).strip().lower()
            scraped_sources.append((name, source_ref, text, source_method))
        except Exception as exc:
            logger.warning("event=scrape_failed source=%s error=%s", name, exc)
            fallback_text = ""
            if url:
                try:
                    fallback_text = _best_effort_fetch_text(url)
                except Exception as fallback_exc:
                    logger.warning(
                        "event=scrape_fallback_failed source=%s error=%s",
                        name,
                        fallback_exc,
                    )
            if fallback_text:
                scraped_sources.append((name, source_ref, fallback_text, "html_fallback"))
            else:
                label = source_ref or name or "<unknown source>"
                scrape_failures.append(f"{label}: {type(exc).__name__}: {exc}")

    if not scraped_sources:
        detail = "; ".join(scrape_failures[:5]).strip()
        if detail:
            raise RuntimeError(f"No sources could be scraped. Failures: {detail}")
        raise RuntimeError("No sources could be scraped.")

    per_source_budget = _source_input_budget(len(scraped_sources))
    source_texts: list[str] = []
    for name, source_ref, text, source_method in scraped_sources:
        source_type = (
            "PDF document"
            if source_method in {"pypdf", "pymupdf", "ocr"} or source_ref.lower().endswith(".pdf")
            else "Web page"
        )
        trimmed = _truncate_for_llm(text, per_source_budget, f"source {name}")
        enforce_sensitive_data_policy(
            trimmed,
            context=f"guide generation source '{name}' ({source_ref})",
            allow_public_contextual_findings=True,
        )
        source_texts.append(
            f"### Source: {name}\n"
            f"Reference: {source_ref}\n"
            f"Source type: {source_type}\n\n"
            f"{trimmed}"
        )

    combined = "\n\n---\n\n".join(source_texts)
    combined = _truncate_for_llm(
        combined,
        MAX_INPUT_CHARS,
        "combined source text",
    )
    enforce_sensitive_data_policy(
        combined,
        context="guide generation combined source text",
        allow_public_contextual_findings=True,
    )

    user_prompt = (
        f'Create a Sponsor Guide for the "{program}" grant program.\n\n'
        f"Below are the scraped source pages:\n\n{combined}"
    )

    logger.info("event=guide_generation_start model=%s", model_name)
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("LLM returned empty content")
    return content
