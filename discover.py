"""Source Discovery module.

Uses Gemini with Google Search grounding to find authoritative web pages
for a given grant program, then validates and classifies each URL.
"""

import json
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.utils.secrets import get_secret

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

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

    prompt = DISCOVERY_PROMPT_TEMPLATE.format(program=program)

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
        print(
            "[discover] No text in grounded response; retrying without Google Search ...",
            file=sys.stderr,
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        raw = _extract_response_text(response)

    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    candidates = json.loads(raw)

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


def build_sources_json(
    program: str,
    candidates: list[dict],
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
        sources.append({
            "name": f"{prefix}_{_make_name(entry['label'])}",
            "url": entry["url"],
            "sections": entry.get("sections", []),
        })
    return sources


if __name__ == "__main__":
    import sys

    program = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "NSF CAREER award"

    print(f"Discovering sources for: {program}\n")

    print("[1/3] Asking Gemini with Google Search grounding ...")
    candidates = discover_sources(program)
    print(f"       Found {len(candidates)} candidate(s)\n")

    print("[2/3] Validating URLs ...")
    candidates = validate_urls(candidates)
    for c in candidates:
        status = "✓" if c.get("reachable") else "✗"
        ct = c.get("content_type", "?")
        print(f"  {status}  [{ct:20s}]  {c['label']:30s}  {c['url']}")
    print()

    print("[3/3] Building sources.json format ...")
    sources = build_sources_json(program, candidates)
    print(json.dumps(sources, indent=2))
