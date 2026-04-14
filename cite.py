"""Citation helper for Sponsor Guide markdown.

Adds footnote citations (with hyperlink references) to guide statements while
enforcing guardrails:
- citations can only reference approved sources from ``sources.json``
- every citation must pass a lexical-overlap validation against source text
- malformed LLM output is safely ignored
"""

import json
import re
from urllib.parse import quote

from openai import OpenAI

import updater
from src.utils.secrets import get_secret


def _tokenize(text: str) -> set[str]:
    """Tokenize text to lowercase alphanumeric words."""
    return set(re.findall(r"[A-Za-z0-9]{3,}", text.lower()))


def _clean_model_json(raw: str) -> str:
    """Strip optional markdown fences from a model JSON response."""
    out = raw.strip()
    out = re.sub(r"^```(?:json)?\s*", "", out)
    out = re.sub(r"\s*```$", "", out)
    return out


def _extract_claim_lines(guide_md: str) -> list[tuple[int, str]]:
    """Return candidate lines that should receive citations.

    Outputs tuples of (line_index, claim_text).
    """
    claims: list[tuple[int, str]] = []
    section_title = ""
    lines = guide_md.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if m:
            section_title = m.group(1).strip().lower()
            continue
        if stripped.startswith("#"):
            continue
        if section_title in {"references", "sources", "resources"}:
            continue
        if re.match(r"^\[(?:\^?[A-Za-z0-9_-]+|\d+)\]:", stripped):
            continue
        if stripped.startswith("|") or re.match(r"^[\s|:-]+$", stripped):
            continue
        if "http://" in stripped or "https://" in stripped:
            continue

        claim = re.sub(r"^[-*]\s+", "", stripped)
        claim = re.sub(r"\[?\[(?:\^?[A-Za-z0-9_-]+|\d+)\]\]?(?:\([^)]+\))?", "", claim).strip()
        if len(claim) < 35:
            continue
        claims.append((idx, claim))
    return claims


def _best_excerpt_and_link(claim: str, source_text: str, base_url: str) -> tuple[str, str]:
    """Return a short evidence excerpt and a best-effort text-fragment deep link."""
    if not source_text:
        return "", base_url

    source_one_line = re.sub(r"\s+", " ", source_text)
    source_lower = source_one_line.lower()
    claim_tokens = sorted(_tokenize(claim), key=len, reverse=True)

    hit_pos = -1
    for tok in claim_tokens:
        hit_pos = source_lower.find(tok)
        if hit_pos >= 0:
            break
    if hit_pos < 0:
        return "", base_url

    start = max(0, hit_pos - 80)
    end = min(len(source_one_line), hit_pos + 220)
    excerpt = source_one_line[start:end].strip()
    excerpt = excerpt[:220].strip()
    if not excerpt:
        return "", base_url

    # Best-effort browser text fragment deep link.
    frag = quote(excerpt[:120], safe="")
    deep_link = f"{base_url}#:~:text={frag}"
    return excerpt, deep_link


def _build_prompt(
    claims: list[tuple[int, str]],
    source_names: list[str],
    source_excerpts: dict[str, str],
) -> str:
    """Create a JSON-only citation prompt for the model."""
    claim_lines = []
    for line_idx, claim in claims:
        claim_lines.append(f'- id: "L{line_idx}" | text: "{claim}"')
    claim_block = "\n".join(claim_lines)

    source_lines = []
    for name in source_names:
        excerpt = source_excerpts.get(name, "")[:900]
        source_lines.append(
            f'- name: "{name}"\n'
            f'  excerpt: "{excerpt}"'
        )
    source_block = "\n".join(source_lines)

    return (
        "Task: map guide claims to approved source names.\n"
        "Rules:\n"
        "1) Use ONLY source names listed below.\n"
        "2) Return ONLY valid JSON (no prose).\n"
        "3) Each item must be {\"id\": \"L<line_index>\", \"sources\": [\"name1\", ...]}.\n"
        "4) Use at most 2 sources per claim.\n"
        "5) If no reliable source exists, omit that claim.\n\n"
        "Claims:\n"
        f"{claim_block}\n\n"
        "Approved sources (with short excerpts):\n"
        f"{source_block}\n"
    )


def add_citations(
    guide_md: str,
    sources: list[dict],
    snapshots_by_name: dict[str, str],
    model_name: str = updater.DEFAULT_MODEL,
    min_overlap: float = 0.06,
) -> tuple[str, list[dict]]:
    """Insert markdown footnote citations with safety guardrails.

    Args:
        guide_md: Updated guide markdown.
        sources: Source registry from ``sources.json``.
        snapshots_by_name: Source-name to scraped page text mapping.
        model_name: Gemini model for citation mapping.
        min_overlap: Minimum lexical-overlap threshold for acceptance.

    Returns:
        Tuple of:
            - cited markdown
            - evidence list suitable for JSON audit export
    """
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        return guide_md, []

    source_url_map = {
        s["name"]: s["url"]
        for s in sources
        if isinstance(s, dict) and s.get("name") and s.get("url")
    }
    if not source_url_map:
        return guide_md, []

    claims = _extract_claim_lines(guide_md)
    if not claims:
        return guide_md, []

    source_names = list(source_url_map.keys())
    source_excerpts = {name: snapshots_by_name.get(name, "") for name in source_names}

    prompt = _build_prompt(claims, source_names, source_excerpts)
    client = OpenAI(api_key=api_key, base_url=updater.GEMINI_BASE_URL)
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "Return strict JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )

    raw = response.choices[0].message.content or ""
    cleaned = _clean_model_json(raw)
    try:
        proposed = json.loads(cleaned)
    except json.JSONDecodeError:
        return guide_md, []

    if not isinstance(proposed, list):
        return guide_md, []

    claim_map = {f"L{idx}": text for idx, text in claims}
    source_tokens = {
        name: _tokenize(snapshots_by_name.get(name, ""))
        for name in source_names
    }

    accepted: dict[int, list[str]] = {}
    source_best_link: dict[str, str] = {}
    evidence: list[dict] = []
    for item in proposed:
        if not isinstance(item, dict):
            continue
        cid = item.get("id")
        cited_sources = item.get("sources", [])
        if not isinstance(cid, str) or cid not in claim_map:
            continue
        if not isinstance(cited_sources, list):
            continue

        filtered = []
        claim_tokens = _tokenize(claim_map[cid])
        if not claim_tokens:
            continue
        for sname in cited_sources[:2]:
            if sname not in source_url_map:
                continue
            stok = source_tokens.get(sname, set())
            if not stok:
                continue
            overlap = len(claim_tokens & stok) / max(1, len(claim_tokens))
            if overlap >= min_overlap:
                filtered.append((sname, overlap))

        if not filtered:
            continue

        line_idx = int(cid[1:])
        accepted[line_idx] = [name for name, _ in filtered]
        enriched_sources: list[dict] = []
        for name, score in filtered:
            excerpt, deep_link = _best_excerpt_and_link(
                claim_map[cid],
                snapshots_by_name.get(name, ""),
                source_url_map[name],
            )
            if name not in source_best_link and deep_link:
                source_best_link[name] = deep_link
            enriched_sources.append(
                {
                    "name": name,
                    "url": source_url_map[name],
                    "deep_link": deep_link,
                    "evidence_excerpt": excerpt,
                    "overlap_score": round(score, 4),
                }
            )

        evidence.append(
            {
                "line_id": cid,
                "claim": claim_map[cid],
                "sources": [name for name, _ in filtered],
                "urls": [source_url_map[name] for name, _ in filtered],
                "source_details": enriched_sources,
                "overlap_scores": {
                    name: round(score, 4)
                    for name, score in filtered
                },
            }
        )

    if not accepted:
        return guide_md, []

    lines = guide_md.splitlines()
    footnote_id_by_source: dict[str, str] = {}
    ordered_sources: list[str] = []

    for line_idx in sorted(accepted.keys()):
        markers: list[str] = []
        for src_name in accepted[line_idx]:
            if src_name not in footnote_id_by_source:
                fid = str(len(footnote_id_by_source) + 1)
                footnote_id_by_source[src_name] = fid
                ordered_sources.append(src_name)
            marker_link = source_best_link.get(src_name, source_url_map[src_name])
            markers.append(f" [[{footnote_id_by_source[src_name]}]]({marker_link})")

        if markers:
            # Strip old markers from prior runs (handles [1](...), [[1]](...),
            # [^S1], [^S1](...) forms) before appending fresh ones.
            base_line = re.sub(
                r"\s*\[?\[(?:\^?[A-Za-z0-9_-]+|\d+)\]\]?(?:\([^)]+\))?",
                "",
                lines[line_idx],
            ).rstrip()
            lines[line_idx] = base_line + "".join(markers)

    if ordered_sources:
        # Remove any existing ## Sources / ## References sections (raw URL lists)
        # to avoid duplication — we rebuild a single References block below.
        _drop_sections = {"sources", "references"}
        filtered: list[str] = []
        dropping = False
        for ln in lines:
            hdr = re.match(r"^#{1,6}\s+(.+)$", ln.strip())
            if hdr:
                dropping = hdr.group(1).strip().lower() in _drop_sections
            if not dropping:
                filtered.append(ln)
        # Remove trailing blank lines so the new section starts cleanly.
        while filtered and not filtered[-1].strip():
            filtered.pop()
        lines = filtered

        lines.append("")
        lines.append("## References")
        lines.append("")
        for src_name in ordered_sources:
            fid = footnote_id_by_source[src_name]
            url = source_best_link.get(src_name, source_url_map[src_name])
            label = src_name.replace("_", " ")
            lines.append(f"\\[{fid}\\]: [{label}]({url})")

    cited_md = "\n".join(lines)
    return cited_md, evidence
