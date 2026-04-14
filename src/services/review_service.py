"""Service wrappers for human source review workflows."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cite
import generator
import review
import scraper
from src.services.persistence_service import (
    hydrate_program,
    list_program_slugs as list_persisted_program_slugs,
    persist_paths,
)
from src.utils.errors import UserFacingError, format_exception


def list_program_slugs() -> list[str]:
    """Return program directory slugs under `programs/`."""
    return list_persisted_program_slugs()


def _metadata_path(slug: str) -> Path:
    return _program_dir(slug) / "metadata.json"


def _display_name_from_slug(slug: str) -> str:
    text = slug.replace("_", " ").strip()
    if not text:
        return slug

    stop_words = {"and", "or", "of", "for", "to", "the", "a", "an", "in", "on", "at", "by", "with"}
    acronyms = {"nsf", "nih", "nasa", "dod", "doe", "usda", "epscor", "sbir", "sttr", "yip", "r01", "r15", "r21"}

    words: list[str] = []
    for idx, raw_word in enumerate(re.sub(r"\s+", " ", text).split(" ")):
        word = raw_word.strip()
        if not word:
            continue
        lower = word.lower()
        if word.isdigit():
            words.append(word)
        elif lower in acronyms:
            words.append(lower.upper())
        elif re.fullmatch(r"[a-z]{2,6}\d*", lower) or re.fullmatch(r"\d+[a-z]*", lower):
            words.append(lower.upper())
        elif lower in stop_words and idx > 0:
            words.append(lower)
        elif len(lower) <= 4 and lower.isalpha():
            words.append(lower.upper())
        else:
            words.append(lower.capitalize())

    return " ".join(words) if words else slug


def get_program_display_name(slug: str) -> str:
    """Return the most readable label we know for a program slug."""
    try:
        hydrate_program(slug)
        metadata_file = _metadata_path(slug)
        if metadata_file.exists():
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            for key in ("program", "display_name", "name"):
                value = str(metadata.get(key, "")).strip()
                if value:
                    return value
    except Exception:
        pass

    return _display_name_from_slug(slug)


def list_program_records() -> list[dict[str, str]]:
    """Return program directories with readable labels for UI pickers."""
    records: list[dict[str, str]] = []
    for slug in list_program_slugs():
        display_name = get_program_display_name(slug)
        records.append(
            {
                "slug": slug,
                "display_name": display_name,
                "label": f"{display_name} ({slug})" if display_name != slug else display_name,
            }
        )

    records.sort(key=lambda item: (item["display_name"].lower(), item["slug"]))
    return records


def _program_dir(slug: str) -> Path:
    return Path("programs") / slug


def _review_dir(slug: str) -> Path:
    return _program_dir(slug) / "review"


def _pending_sources_path(slug: str) -> Path:
    return _review_dir(slug) / "sources_pending.json"


def _draft_guide_path(slug: str) -> Path:
    return _review_dir(slug) / "draft_guide.md"


def _baseline_guide_path(slug: str) -> Path:
    return _program_dir(slug) / "guide.md"


def draft_exists(slug: str) -> bool:
    """Return True when a review draft exists for a program."""
    hydrate_program(slug)
    return _draft_guide_path(slug).exists()


def _decisions_path(slug: str) -> Path:
    return _review_dir(slug) / "review_decisions.json"


def _manual_sources_path(slug: str) -> Path:
    return _review_dir(slug) / "manual_sources.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_manual_name(slug: str, title: str, url: str) -> str:
    token = title.strip() or url.strip().split("//")[-1].split("/")[0] or "source"
    safe = "".join(ch if ch.isalnum() else "_" for ch in token).strip("_") or "source"
    return f"{slug}_manual_{safe}".lower()


def clean_optional_text(value: Any) -> str | None:
    """Normalize optional text fields and common missing-value markers."""
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if v.lower() in {"n/a", "na", "none", "unknown", "tbd"}:
        return None
    return v


# Key Dates should be short; pathological LLM output can be one multi-megabyte "table" line.
_MAX_KEY_DATES_LINE_CHARS = 2000
_MAX_KEY_DATES_BODY_CHARS = 12000


def _key_dates_body_needs_fallback(body: str) -> bool:
    """True when the section is empty, shell-only, or padded/malformed markdown tables."""
    non_empty = [ln.strip() for ln in body.splitlines() if ln.strip()]

    if len(non_empty) >= 2 and non_empty[0].startswith("|") and set(non_empty[1]) <= set("|:- "):
        has_data_rows = any(ln.startswith("|") and ln.count("|") >= 2 for ln in non_empty[2:])
        if not has_data_rows:
            return True

    if clean_optional_text(body) is None:
        return True

    if any(len(ln) > _MAX_KEY_DATES_LINE_CHARS for ln in body.splitlines()):
        return True
    if len(body) > _MAX_KEY_DATES_BODY_CHARS:
        return True

    # One long pipe row with no separator/newlines (invalid table, often space-padding).
    if len(non_empty) == 1 and non_empty[0].lstrip().startswith("|") and len(non_empty[0]) > 400:
        return True

    return False


def _sanitize_key_dates_section(guide_md: str) -> str:
    """Ensure Key Dates section has non-empty body and no empty table shell."""
    heading_re = re.compile(r"^##\s*(?:3\.?\s*)?Key Dates\s*$", re.IGNORECASE | re.MULTILINE)
    match = heading_re.search(guide_md)
    if not match:
        return guide_md

    body_start = match.end()
    next_heading = re.search(r"^##\s+", guide_md[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(guide_md)
    body = guide_md[body_start:body_end]

    if not _key_dates_body_needs_fallback(body):
        return guide_md

    fallback = (
        "\n\n"
        "- **Deadline:** No specific deadline listed on the sponsor website.\n"
        "- **Recommendation:** Verify the timeline with the sponsor page or program contact.\n"
    )
    return guide_md[:match.end()] + fallback + guide_md[body_end:]


def _sanitize_generated_guide_markdown(guide_md: str) -> str:
    """Normalize generated markdown to avoid empty sections and large blank blocks."""
    cleaned = _sanitize_key_dates_section(guide_md)
    # Collapse excessive blank lines so headings do not render with large empty gaps.
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned


def add_manual_source(
    slug: str,
    url: str,
    title: str = "",
    mapped_section: str = "",
    reviewer_note: str = "",
) -> dict[str, Any]:
    """Persist a manually added source in a review sidecar JSON file."""
    try:
        hydrate_program(slug)
        clean_url = url.strip()
        if not clean_url:
            raise UserFacingError("URL is required.")

        review_dir = _review_dir(slug)
        review_dir.mkdir(parents=True, exist_ok=True)

        manual_path = _manual_sources_path(slug)
        manual_sources: list[dict[str, Any]] = []
        if manual_path.exists():
            manual_sources = json.loads(manual_path.read_text(encoding="utf-8"))

        name = _make_manual_name(slug, title, clean_url)
        existing_names = {entry.get("name", "") for entry in manual_sources}
        suffix = 2
        base_name = name
        while name in existing_names:
            name = f"{base_name}_{suffix}"
            suffix += 1

        sections = [mapped_section.strip()] if mapped_section.strip() else []
        entry = {
            "name": name,
            "url": clean_url,
            "title": title.strip(),
            "sections": sections,
            "mapped_section": mapped_section.strip(),
            "note": reviewer_note.strip(),
            "source_origin": "manual",
            "created_at": _utc_now(),
            "review_status": "approved",
        }
        manual_sources.append(entry)
        manual_path.write_text(json.dumps(manual_sources, indent=2), encoding="utf-8")
        storage = persist_paths(slug, ["review/manual_sources.json"])
        return {"ok": True, "entry": entry, "path": str(manual_path), "storage": storage}
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to add manual source.", "detail": format_exception(exc)}


def load_review_context(slug: str) -> dict[str, Any]:
    """Load candidate sources plus any saved review decisions for a program."""
    try:
        hydrate_program(slug)
        pending_path = _pending_sources_path(slug)
        if pending_path.exists():
            sources = json.loads(pending_path.read_text(encoding="utf-8"))
        else:
            fallback_sources = _program_dir(slug) / "sources.json"
            if not fallback_sources.exists():
                raise UserFacingError("No pending or approved sources found for this program.")
            sources = json.loads(fallback_sources.read_text(encoding="utf-8"))

        decisions_file = _decisions_path(slug)
        decisions = {}
        if decisions_file.exists():
            decisions = json.loads(decisions_file.read_text(encoding="utf-8"))

        manual_file = _manual_sources_path(slug)
        manual_sources: list[dict[str, Any]] = []
        if manual_file.exists():
            manual_sources = json.loads(manual_file.read_text(encoding="utf-8"))

        rows: list[dict[str, Any]] = []
        for src in sources:
            name = src.get("name", "")
            decision = decisions.get(name, {})
            rows.append(
                {
                    "name": name,
                    "url": src.get("url", ""),
                    "sections": src.get("sections", []),
                    "status": decision.get("status", "unreviewed"),
                    "notes": decision.get("notes", ""),
                    "source_origin": "auto",
                    "title": src.get("title", ""),
                    "created_at": "",
                }
            )

        for src in manual_sources:
            name = src.get("name", "")
            decision = decisions.get(name, {})
            rows.append(
                {
                    "name": name,
                    "url": src.get("url", ""),
                    "sections": src.get("sections", []),
                    "status": decision.get("status", src.get("review_status", "approved")),
                    "notes": decision.get("notes", src.get("note", "")),
                    "source_origin": "manual",
                    "title": src.get("title", ""),
                    "created_at": src.get("created_at", ""),
                }
            )

        return {"ok": True, "slug": slug, "rows": rows, "decisions": decisions}
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to load review context.", "detail": format_exception(exc)}


def save_review_decision(slug: str, source_name: str, status: str, notes: str = "") -> dict[str, Any]:
    """Save approve/reject decision metadata for one source."""
    try:
        hydrate_program(slug)
        if status not in {"approved", "rejected", "unreviewed", "pending_manual_review"}:
            raise UserFacingError("Invalid review status.")

        review_dir = _review_dir(slug)
        review_dir.mkdir(parents=True, exist_ok=True)
        decisions_file = _decisions_path(slug)

        decisions: dict[str, Any] = {}
        if decisions_file.exists():
            decisions = json.loads(decisions_file.read_text(encoding="utf-8"))

        decisions[source_name] = {"status": status, "notes": notes.strip()}
        decisions_file.write_text(json.dumps(decisions, indent=2), encoding="utf-8")
        storage = persist_paths(slug, ["review/review_decisions.json"])
        return {"ok": True, "path": str(decisions_file), "storage": storage}
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to save review decision.", "detail": format_exception(exc)}


def finalize_review(slug: str, include_unreviewed: bool = False) -> dict[str, Any]:
    """Finalize review decisions into program `sources.json` only."""
    try:
        hydrate_program(slug)
        context = load_review_context(slug)
        if not context["ok"]:
            return context

        approved_sources = []
        for row in context["rows"]:
            status = row["status"]
            if status == "approved" or (
                include_unreviewed and status in {"unreviewed", "pending_manual_review"}
            ):
                approved_sources.append(
                    {"name": row["name"], "url": row["url"], "sections": row["sections"]}
                )

        if not approved_sources:
            raise UserFacingError("No sources selected for finalization.")

        program_dir = _program_dir(slug)
        program_dir.mkdir(parents=True, exist_ok=True)
        sources_out = program_dir / "sources.json"
        sources_out.write_text(json.dumps(approved_sources, indent=2), encoding="utf-8")
        storage = persist_paths(slug, ["sources.json"])
        return {
            "ok": True,
            "approved_count": len(approved_sources),
            "sources_out": str(sources_out),
            "guide_out": "",
            "storage": storage,
        }
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to finalize review.", "detail": format_exception(exc)}


def generate_first_draft(slug: str, with_citations: bool = True) -> dict[str, Any]:
    """Generate the first guide draft (with citations) and write output files."""
    try:
        hydrate_program(slug)
        program_dir = _program_dir(slug)
        sources_path = program_dir / "sources.json"
        if not sources_path.exists():
            raise UserFacingError("No approved sources found. Finalize sources before generating first draft.")

        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        if not isinstance(sources, list) or not sources:
            raise UserFacingError("Approved sources file is empty or invalid.")

        guide_md = generator.generate_guide(sources, slug)
        guide_md = _sanitize_generated_guide_markdown(guide_md)

        evidence: list[dict] = []
        citation_count = 0
        if with_citations:
            snapshot_map: dict[str, str] = {}
            for src in sources:
                try:
                    snapshot_map[src["name"]] = scraper.fetch_and_clean_text(src["url"])
                except Exception:
                    snapshot_map[src["name"]] = ""
            try:
                cited_md, evidence = cite.add_citations(
                    guide_md,
                    sources=sources,
                    snapshots_by_name=snapshot_map,
                )
                if evidence:
                    guide_md = cited_md
                    citation_count = len(evidence)
            except Exception:
                pass

        review_dir = _review_dir(slug)
        review_dir.mkdir(parents=True, exist_ok=True)
        draft_path = review_dir / "draft_guide.md"
        draft_path.write_text(guide_md, encoding="utf-8")

        output_dir = program_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_output_files(guide_md, evidence, output_dir)

        persist_files = ["review/draft_guide.md", "output/sponsor_guide_updated.md"]
        if (output_dir / "sponsor_guide_updated.docx").exists():
            persist_files.append("output/sponsor_guide_updated.docx")
        if (output_dir / "sponsor_guide_updated.pdf").exists():
            persist_files.append("output/sponsor_guide_updated.pdf")
        if (output_dir / "sponsor_guide_evidence.json").exists():
            persist_files.append("output/sponsor_guide_evidence.json")
        storage = persist_paths(slug, persist_files)

        return {
            "ok": True,
            "slug": slug,
            "sources_path": str(sources_path),
            "draft_path": str(draft_path),
            "draft_chars": len(guide_md),
            "citation_count": citation_count,
            "output_dir": str(output_dir),
            "storage": storage,
        }
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to generate first draft.", "detail": format_exception(exc)}


def _write_output_files(
    guide_md: str, evidence: list[dict], output_dir: Path
) -> None:
    """Write md, docx, pdf, and evidence.json output files."""
    import pipeline

    md_path = output_dir / "sponsor_guide_updated.md"
    md_path.write_text(guide_md, encoding="utf-8")

    docx_path = output_dir / "sponsor_guide_updated.docx"
    try:
        pipeline._md_to_docx(guide_md, str(docx_path))
    except Exception:
        pass

    try:
        pdf_path = output_dir / "sponsor_guide_updated.pdf"
        pipeline._md_to_pdf(guide_md, str(pdf_path))
    except Exception:
        pass

    if evidence:
        evidence_path = output_dir / "sponsor_guide_evidence.json"
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


def promote_draft_to_baseline(slug: str) -> dict[str, Any]:
    """Promote review draft markdown to program baseline guide.md."""
    try:
        hydrate_program(slug)
        draft_path = _draft_guide_path(slug)
        if not draft_path.exists():
            raise UserFacingError(
                "Draft guide not found. Generate the first draft before promoting to baseline."
            )

        baseline_path = _baseline_guide_path(slug)
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        content = _sanitize_generated_guide_markdown(draft_path.read_text(encoding="utf-8"))
        baseline_path.write_text(content, encoding="utf-8")
        storage = persist_paths(slug, ["guide.md"])

        return {
            "ok": True,
            "draft_path": str(draft_path),
            "baseline_path": str(baseline_path),
            "chars_copied": len(content),
            "message": "Draft promoted to baseline guide.md.",
            "storage": storage,
        }
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to promote draft.", "detail": format_exception(exc)}
