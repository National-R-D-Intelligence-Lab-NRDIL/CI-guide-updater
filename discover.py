"""Source Discovery module.

Uses Gemini with Google Search grounding to find authoritative web pages
for a given grant program, then validates and classifies each URL.
"""
# Intentionally bypasses llm_client: this module uses Gemini-specific Google Search grounding.

import json
import logging
import re
import sys
from typing import Any, Optional, Set, Tuple

import requests
from google import genai
from google.genai import types

from src.utils.secrets import get_secret
from src.utils.logging_utils import configure_rotating_file_logging
from src.utils.source_policy import sanitize_program_for_prompt

DISCOVERY_PROMPT_TEMPLATE = """\
Find the most important official web pages for the "{program}" \
grant program. I need CURRENT, WORKING URLs (as of 2026) that contain:

1. The main program overview page
2. The current solicitation / Notice of Funding Opportunity (NOFO) — use \
the LATEST solicitation number if multiple exist
3. Eligibility requirements
4. Award amounts and budget details
5. Application deadlines and due dates
6. Review criteria and review process
7. Application guide / proposal preparation instructions
8. FAQ page for this specific program
9. Any other key policy pages a proposal writer would need

IMPORTANT URL RULES:
- Use the CURRENT live URLs. Many agencies have migrated websites \
(e.g. NSF moved from www.nsf.gov/pubs/... to new.nsf.gov/...).
- Prefer canonical page URLs over anchor links (no #section fragments).
- Do NOT return PDF URLs — only HTML pages.
- Each URL must be a complete, absolute URL starting with https://.

For each page, return:
- The exact URL
- A short label (2-5 words)
- Which guide sections it would inform (pick from: Program Overview, \
Eligibility, Key Dates, Award Size, Review Criteria, Application \
Requirements, Resources, Tips, FAQ)

Return ONLY a JSON array. Each element must have keys: "url", "label", \
"sections". No markdown fences, no commentary — just the JSON array.
"""

ALTERNATIVE_FUNDING_SEED_CATALOG: list[dict[str, Any]] = [
    {
        "label": "Wellcome Funding Opportunities",
        "url": "https://wellcome.org/grant-funding/schemes",
        "sections": ["Program Overview", "Eligibility", "Key Dates", "Award Size", "Resources"],
        "funding_type": "international",
        "funder_name": "Wellcome Trust",
        "focus_areas": ["global health", "biomedical research"],
        "geography": "global",
        "source_authority": 1.0,
    },
    {
        "label": "Gates Foundation Grant Opportunities",
        "url": "https://www.gatesfoundation.org/about/how-we-work/grant-opportunities",
        "sections": ["Program Overview", "Eligibility", "Key Dates", "Application Requirements"],
        "funding_type": "foundation",
        "funder_name": "Gates Foundation",
        "focus_areas": ["health", "development", "innovation"],
        "geography": "global",
        "source_authority": 1.0,
    },
    {
        "label": "Bloomberg Philanthropies Funding",
        "url": "https://www.bloomberg.org/",
        "sections": ["Program Overview", "Eligibility", "Resources"],
        "funding_type": "foundation",
        "funder_name": "Bloomberg Philanthropies",
        "focus_areas": ["public health", "cities", "policy"],
        "geography": "global",
        "source_authority": 0.95,
    },
    {
        "label": "Pfizer Research Partnerships",
        "url": "https://www.pfizer.com/science/research-development",
        "sections": ["Program Overview", "Eligibility", "Application Requirements", "Resources"],
        "funding_type": "pharma_partnership",
        "funder_name": "Pfizer",
        "focus_areas": ["biopharma", "clinical research"],
        "geography": "global",
        "source_authority": 0.9,
    },
    {
        "label": "Roche Partnering and Innovation",
        "url": "https://www.roche.com/partnering",
        "sections": ["Program Overview", "Eligibility", "Application Requirements", "Resources"],
        "funding_type": "pharma_partnership",
        "funder_name": "Roche",
        "focus_areas": ["drug development", "diagnostics"],
        "geography": "global",
        "source_authority": 0.9,
    },
]

logger = logging.getLogger(__name__)


def _extract_response_text(response) -> str:
    """Return model text or raise with a clear reason (Gemini may return ``None``)."""
    text = getattr(response, "text", None)
    if text is not None and str(text).strip():
        return str(text).strip()

    details: list[str] = []

    pf = getattr(response, "prompt_feedback", None)
    if pf is not None:
        br = getattr(pf, "block_reason", None)
        if br is not None:
            details.append(f"prompt_feedback.block_reason={br}")
        msg = getattr(pf, "block_reason_message", None)
        if msg:
            details.append(str(msg))

    cands = getattr(response, "candidates", None) or []
    for i, cand in enumerate(cands):
        fr = getattr(cand, "finish_reason", None)
        if fr is not None:
            details.append(f"candidate[{i}].finish_reason={fr}")
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if parts:
            for part in parts:
                t = getattr(part, "text", None)
                if isinstance(t, str) and t.strip():
                    return t.strip()

    if not details:
        details.append("no text parts and no candidates (or empty content)")

    raise RuntimeError(
        "Gemini returned no usable text for source discovery. "
        + " ".join(details)
        + " Try a shorter program name, retry later, or add sources manually to sources.json."
    )


def _parse_candidates_json(raw: str) -> list[dict]:
    """Parse model output into a candidate list with clear errors.

    Gemini occasionally returns empty text or a short explanation instead of a
    strict JSON payload. We keep parsing defensive so callers get a meaningful
    message instead of a low-level JSONDecodeError.
    """
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    if not cleaned:
        raise RuntimeError(
            "Source discovery returned an empty response. "
            "Retry in a moment, or add sources manually in Review Sources."
        )

    # Try to recover a JSON array if extra explanation surrounds the payload.
    if not cleaned.startswith("["):
        array_match = re.search(r"\[[\s\S]*\]", cleaned)
        if array_match:
            cleaned = array_match.group(0)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        snippet = cleaned[:200].replace("\n", " ")
        raise RuntimeError(
            "Source discovery returned non-JSON output. "
            f"Could not parse model response: {exc.msg}. "
            f"Response snippet: {snippet!r}"
        ) from exc

    if not isinstance(parsed, list):
        raise RuntimeError("Source discovery response must be a JSON array.")

    candidates: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if not item.get("url") or not item.get("label"):
            continue
        if not isinstance(item.get("sections"), list):
            item["sections"] = []
        candidates.append(item)

    if not candidates:
        raise RuntimeError(
            "Source discovery returned no usable candidates. "
            "Retry or add sources manually in Review Sources."
        )

    return candidates


def discover_sources(program: str) -> list[dict]:
    """Use Gemini + Google Search grounding to find source URLs.

    Args:
        program: Grant program name, e.g. ``"NSF CAREER award"``.

    Returns:
        List of dicts with ``url``, ``label``, ``sections``, and
        ``grounded`` (whether the URL came from search results).
    """
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=api_key)

    prompt_program = sanitize_program_for_prompt(program)
    if not prompt_program:
        raise ValueError("Program name is required for source discovery.")
    prompt = DISCOVERY_PROMPT_TEMPLATE.format(program=prompt_program)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
        ),
    )

    try:
        raw = _extract_response_text(response)
    except RuntimeError:
        # Google Search grounding sometimes yields no text parts; retry without tools.
        logger.warning(
            "event=discover_retry_without_grounding reason=no_text_from_grounded_response"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        raw = _extract_response_text(response)

    candidates = _parse_candidates_json(raw)

    grounded_urls: set[str] = set()
    metadata = getattr(response, "candidates", [])
    if metadata:
        gm = getattr(metadata[0], "grounding_metadata", None)
        if gm:
            chunks = getattr(gm, "grounding_chunks", []) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    grounded_urls.add(web.uri)

    for entry in candidates:
        entry["grounded"] = entry["url"] in grounded_urls

    return candidates


def validate_urls(candidates: list[dict]) -> list[dict]:
    """Check each candidate URL; follow redirects, record final URL.

    Uses GET (not HEAD) because some servers return different status codes
    for HEAD requests. Only reads headers (stream mode).

    Args:
        candidates: Output of :func:`discover_sources`.

    Returns:
        Same list with added ``status``, ``content_type``, ``reachable``,
        and ``final_url`` keys. ``url`` is updated to the final URL if
        a redirect occurred.
    """
    seen: set[str] = set()
    for entry in candidates:
        try:
            r = requests.get(entry["url"], timeout=15, allow_redirects=True, stream=True)
            r.close()
            entry["status"] = r.status_code
            entry["content_type"] = r.headers.get("content-type", "").split(";")[0].strip()
            entry["reachable"] = r.status_code == 200
            if r.url != entry["url"]:
                entry["final_url"] = r.url
                entry["url"] = r.url
        except Exception as exc:
            entry["status"] = 0
            entry["content_type"] = ""
            entry["reachable"] = False
            entry["error"] = str(exc)

        if entry["url"] in seen:
            entry["reachable"] = False
            entry["duplicate"] = True
        else:
            seen.add(entry["url"])

    return candidates


def _make_name(label: str) -> str:
    """Convert a human label to a safe identifier, e.g. 'Main Overview' -> 'Main_Overview'."""
    return re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")


def _normalize_tokens(values: Optional[list[str]]) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    for value in values:
        token = re.sub(r"\s+", " ", str(value).strip().lower())
        if token:
            normalized.append(token)
    return normalized


def _infer_funding_type(label: str, url: str) -> str:
    text = f"{label} {url}".lower()
    if any(word in text for word in ["partner", "pharma", "clinical", "biotech", "drug"]):
        return "pharma_partnership"
    if any(word in text for word in ["international", "global", "world"]):
        return "international"
    if any(word in text for word in ["corporate", "industry"]):
        return "corporate"
    return "foundation"


def _infer_funder_name(url: str, label: str) -> str:
    text = f"{label} {url}".lower()
    aliases = {
        "wellcome": "Wellcome Trust",
        "gates": "Gates Foundation",
        "bloomberg": "Bloomberg Philanthropies",
        "pfizer": "Pfizer",
        "roche": "Roche",
        "novartis": "Novartis",
        "merck": "Merck",
    }
    for key, value in aliases.items():
        if key in text:
            return value
    domain = re.sub(r"^https?://", "", url).split("/")[0]
    return domain.replace("www.", "")


def score_opportunity(
    program: str,
    candidate: dict[str, Any],
    sectors: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    tracked_urls: Optional[Set[str]] = None,
) -> Tuple[int, float]:
    """Score a source candidate as an alternative-funding opportunity."""
    sectors_norm = _normalize_tokens(sectors)
    regions_norm = _normalize_tokens(regions)
    tracked = tracked_urls or set()
    blob = " ".join(
        [
            program,
            str(candidate.get("label", "")),
            str(candidate.get("url", "")),
            " ".join(candidate.get("sections", []) or []),
            " ".join(candidate.get("focus_areas", []) or []),
            str(candidate.get("geography", "")),
        ]
    ).lower()

    relevance = 0.5
    if sectors_norm and any(sector in blob for sector in sectors_norm):
        relevance += 0.2
    if regions_norm and any(region in blob for region in regions_norm):
        relevance += 0.1
    if any(keyword in blob for keyword in ["deadline", "apply", "funding", "grant", "rfp", "opportun"]):
        relevance += 0.1

    authority = float(candidate.get("source_authority", 0.75))
    novelty = 0.0 if candidate.get("url", "") in tracked else 0.1
    urgency = 0.1 if candidate.get("deadline") else 0.0

    confidence = max(0.0, min(1.0, relevance + (authority - 0.7) * 0.4))
    priority = int(round(max(0.0, min(1.0, relevance + authority * 0.2 + novelty + urgency)) * 100))
    return priority, round(confidence, 3)


def discover_alternative_funding_sources(
    program: str,
    sectors: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Discover and rank non-federal alternative funding opportunities."""
    enriched_prompt = (
        f"{program} foundation corporate international funding opportunities "
        "Wellcome Trust Gates Foundation Bloomberg Philanthropies pharma partnerships"
    )
    discovered = discover_sources(enriched_prompt)
    merged: list[dict[str, Any]] = [*ALTERNATIVE_FUNDING_SEED_CATALOG, *discovered]
    validated = validate_urls(merged)

    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for entry in validated:
        url = str(entry.get("url", "")).strip()
        if not url or url in seen or not entry.get("reachable"):
            continue
        seen.add(url)
        entry["funding_type"] = entry.get("funding_type") or _infer_funding_type(
            str(entry.get("label", "")), url
        )
        entry["funder_name"] = entry.get("funder_name") or _infer_funder_name(
            url, str(entry.get("label", ""))
        )
        entry["focus_areas"] = entry.get("focus_areas") or []
        entry["geography"] = entry.get("geography") or ""
        entry["deadline"] = entry.get("deadline")
        entry["typical_award_size"] = entry.get("typical_award_size")
        entry["eligibility_summary"] = entry.get("eligibility_summary", "")
        priority, confidence = score_opportunity(
            program=program,
            candidate=entry,
            sectors=sectors,
            regions=regions,
        )
        entry["priority_score"] = priority
        entry["confidence_score"] = confidence
        ranked.append(entry)

    ranked.sort(key=lambda row: (row.get("priority_score", 0), row.get("confidence_score", 0.0)), reverse=True)
    return ranked


def build_alternative_funding_monitor(
    program: str,
    sectors: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build ranked alternative-funding monitor candidates and sources payload."""
    ranked = discover_alternative_funding_sources(program=program, sectors=sectors, regions=regions)
    sources = build_sources_json(program, ranked, include_metadata=True)
    return {"candidates": ranked, "sources": sources}


def build_sources_json(
    program: str,
    candidates: list[dict],
    *,
    include_metadata: bool = False,
) -> list[dict]:
    """Convert validated candidates into sources.json format.

    Filters to reachable HTML pages only.

    Args:
        program: Program name used as a prefix.
        candidates: Validated candidate list.

    Returns:
        List of dicts ready to write to ``sources.json``.
    """
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", program).strip("_")
    sources = []
    for entry in candidates:
        if not entry.get("reachable"):
            continue
        ct = entry.get("content_type", "")
        if "html" not in ct and "text" not in ct:
            continue
        item = {
            "name": f"{prefix}_{_make_name(entry['label'])}",
            "url": entry["url"],
            "sections": entry.get("sections", []),
            "data_class": "public",
        }
        if include_metadata:
            for key in (
                "funding_type",
                "funder_name",
                "opportunity_title",
                "focus_areas",
                "geography",
                "deadline",
                "typical_award_size",
                "eligibility_summary",
                "confidence_score",
                "priority_score",
            ):
                if key in entry:
                    item[key] = entry.get(key)
            if not item.get("opportunity_title"):
                item["opportunity_title"] = entry.get("label", "")
        sources.append(item)
    return sources


if __name__ == "__main__":
    program = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "NSF CAREER award"
    configure_rotating_file_logging(log_file="logs/discover.log")

    logger.info("discover_start program=%s", program)

    logger.info("step=1 action=query_model status=start")
    candidates = discover_sources(program)
    logger.info("step=1 action=query_model status=done candidates=%d", len(candidates))

    logger.info("step=2 action=validate_urls status=start")
    candidates = validate_urls(candidates)
    for c in candidates:
        status = "✓" if c.get("reachable") else "✗"
        ct = c.get("content_type", "?")
        logger.info(
            "step=2 candidate_status=%s content_type=%s label=%s url=%s",
            status,
            ct,
            c["label"],
            c["url"],
        )

    logger.info("step=3 action=build_sources_json status=start")
    sources = build_sources_json(program, candidates)
    logger.info("step=3 action=build_sources_json status=done sources=%s", json.dumps(sources))
