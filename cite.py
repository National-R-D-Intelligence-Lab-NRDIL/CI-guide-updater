"""Citation helper for Sponsor Guide markdown.

Adds footnote citations (with hyperlink references) to guide statements while
enforcing guardrails:
- citations can only reference approved sources from ``sources.json``
- every citation must pass a lexical-overlap validation against source text
- malformed LLM output is safely ignored
"""

import json
import re
from typing import Optional
from urllib.parse import quote

from src.utils.llm_client import get_default_model, get_llm_client
from src.utils.sensitive_data import enforce_sensitive_data_policy
from src.utils.source_policy import assert_public_sources


def _tokenize(text: str) -> set[str]:
    """Tokenize text to lowercase alphanumeric words."""
    return set(re.findall(r"[A-Za-z0-9]{3,}", text.lower()))


def _clean_model_json(raw: str) -> str:
    """Strip optional markdown fences from a model JSON response."""
    out = raw.strip()
    out = re.sub(r"^```(?:json)?\s*", "", out)
    out = re.sub(r"\s*```$", "", out)
    return out


def _strip_html_tags(text: str) -> str:
    """Remove lightweight HTML markup before citation claim matching."""
    return re.sub(r"<[^>]+>", "", text)


def _extract_claim_lines(guide_md: str) -> list[tuple[int, str]]:
    """Return candidate lines that should receive citations.

    Outputs tuples of (line_index, claim_text).
    """
    claims: list[tuple[int, str]] = []
    section_title = ""
    in_weekly_banner = False
    lines = guide_md.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "<!-- weekly-update-banner:start -->":
            in_weekly_banner = True
            continue
        if stripped == "<!-- weekly-update-banner:end -->":
            in_weekly_banner = False
            continue
        if in_weekly_banner:
            continue
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
        claim = _strip_html_tags(claim).strip()
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
    if base_url.startswith("http://") or base_url.startswith("https://"):
        frag = quote(excerpt[:120], safe="")
        deep_link = f"{base_url}#:~:text={frag}"
    else:
        deep_link = base_url
    return excerpt, deep_link


def _chunk_text(text: str, chunk_size: int = 900) -> list[str]:
    """Split large source text into compact chunks for relevance scoring."""
    one_line = re.sub(r"\s+", " ", text).strip()
    if not one_line:
        return []
    return [one_line[i : i + chunk_size] for i in range(0, len(one_line), chunk_size)]


def _select_relevant_source_excerpt(
    source_text: str,
    claims: list[tuple[int, str]],
    max_chars: int = 2200,
) -> str:
    """Select source excerpts most likely to support the guide claims.

    Long PDFs can be hundreds of thousands of characters. Sending only the
    opening page hides the sections that contain eligibility, budget, and
    application details, so we rank chunks by token overlap with all claims.
    """
    if len(source_text) <= max_chars:
        return source_text

    claim_tokens = set()
    for _, claim in claims:
        claim_tokens.update(_tokenize(claim))
    if not claim_tokens:
        return source_text[:max_chars]

    chunks = _chunk_text(source_text)
    scored: list[tuple[int, int, str]] = []
    for idx, chunk in enumerate(chunks):
        score = len(_tokenize(chunk) & claim_tokens)
        if score:
            scored.append((score, idx, chunk))

    if not scored:
        return source_text[:max_chars]

    selected: list[str] = []
    used = 0
    for _, _, chunk in sorted(scored, key=lambda item: (-item[0], item[1])):
        separator = "\n...\n" if selected else ""
        candidate_len = len(separator) + len(chunk)
        if used + candidate_len > max_chars:
            remaining = max_chars - used - len(separator)
            if remaining > 200:
                selected.append(separator + chunk[:remaining])
            break
        selected.append(separator + chunk)
        used += candidate_len
        if len(selected) >= 3:
            break

    return "".join(selected) if selected else source_text[:max_chars]


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
        excerpt = source_excerpts.get(name, "")[:2200]
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
    source_metadata_by_name: Optional[dict[str, dict]] = None,
    model_name: Optional[str] = None,
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
    try:
        client = get_llm_client()
    except EnvironmentError:
        return guide_md, []
    if model_name is None:
        model_name = get_default_model()

    assert_public_sources(sources, context="citation generation")

    source_url_map = {}
    for s in sources:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        ref = str(s.get("url", "")).strip() or str(s.get("file_path", "")).strip()
        if ref:
            source_url_map[name] = ref
    source_metadata_by_name = source_metadata_by_name or {}
    if not source_url_map:
        return guide_md, []

    claims = _extract_claim_lines(guide_md)
    if not claims:
        return guide_md, []

    source_names = list(source_url_map.keys())
    source_excerpts = {
        name: _select_relevant_source_excerpt(snapshots_by_name.get(name, ""), claims)
        for name in source_names
    }
    for name, excerpt in source_excerpts.items():
        enforce_sensitive_data_policy(
            excerpt,
            context=f"citation generation source '{name}'",
        )

    prompt = _build_prompt(claims, source_names, source_excerpts)
    enforce_sensitive_data_policy(
        prompt,
        context="citation generation prompt",
    )
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
                    "extraction": source_metadata_by_name.get(name, {}),
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
