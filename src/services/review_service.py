"""Service wrappers for human source review workflows."""

from __future__ import annotations

import json
import logging
import re
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import generator
import review

logger = logging.getLogger(__name__)
from src.services.persistence_service import (
    hydrate_program,
    list_program_slugs as list_persisted_program_slugs,
    persist_paths,
)
from src.utils.errors import UserFacingError, format_exception
from src.utils.sensitive_data import SensitiveDataError, format_sensitive_data_error
from src.utils.source_policy import assert_public_sources, normalize_and_validate_public_url


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


_SOURCE_BASE_FIELDS = {
    "name",
    "url",
    "file_path",
    "sections",
    "data_class",
    "title",
    "status",
    "notes",
    "source_origin",
    "created_at",
}


def _make_manual_name(slug: str, title: str, url: str) -> str:
    token = title.strip() or url.strip().split("//")[-1].split("/")[0] or "source"
    safe = "".join(ch if ch.isalnum() else "_" for ch in token).strip("_") or "source"
    return f"{slug}_manual_{safe}".lower()


def _unique_source_name(base_name: str, existing_names: set[str]) -> str:
    """Return a source name that does not collide with existing entries."""
    name = base_name
    suffix = 2
    while name in existing_names:
        name = f"{base_name}_{suffix}"
        suffix += 1
    return name


def _sources_path(slug: str) -> Path:
    return _program_dir(slug) / "sources.json"


def _load_sources_json(slug: str) -> list[dict[str, Any]]:
    """Load the approved sources list for a program."""
    sources_path = _sources_path(slug)
    if not sources_path.exists():
        raise UserFacingError("Approved sources not found for selected program.")
    data = json.loads(sources_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise UserFacingError("Approved sources file is invalid.", "sources.json must contain a JSON array.")
    return [src for src in data if isinstance(src, dict)]


def _write_sources_json(slug: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Write and persist the approved sources list."""
    sources_path = _sources_path(slug)
    sources_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.write_text(json.dumps(sources, indent=2), encoding="utf-8")
    storage = persist_paths(slug, ["sources.json"])
    return {"path": str(sources_path), "storage": storage}


def _clean_sections(sections_text: str | list[Any]) -> list[str]:
    """Normalize comma/newline-separated section labels."""
    if isinstance(sections_text, list):
        raw_items = [str(item) for item in sections_text]
    else:
        raw_items = re.split(r"[,\n]", str(sections_text or ""))
    return [item.strip() for item in raw_items if item.strip()]


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
    data_class: str = "public",
) -> dict[str, Any]:
    """Persist a manually added source in a review sidecar JSON file."""
    try:
        hydrate_program(slug)
        clean_url = url.strip()
        if not clean_url:
            raise UserFacingError("URL is required.")
        try:
            clean_url = normalize_and_validate_public_url(clean_url, context="manual source")
        except ValueError as exc:
            raise UserFacingError("Invalid or untrusted URL.", str(exc)) from exc
        clean_data_class = str(data_class).strip().lower()
        if clean_data_class not in {"public", "internal"}:
            raise UserFacingError("Invalid data class.", "Choose public or internal.")

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
        review_status = "approved" if clean_data_class == "public" else "pending_manual_review"
        entry = {
            "name": name,
            "url": clean_url,
            "title": title.strip(),
            "sections": sections,
            "data_class": clean_data_class,
            "mapped_section": mapped_section.strip(),
            "note": reviewer_note.strip(),
            "source_origin": "manual",
            "created_at": _utc_now(),
            "review_status": review_status,
        }
        manual_sources.append(entry)
        manual_path.write_text(json.dumps(manual_sources, indent=2), encoding="utf-8")
        storage = persist_paths(slug, ["review/manual_sources.json"])
        return {"ok": True, "entry": entry, "path": str(manual_path), "storage": storage}
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to add manual source.", "detail": format_exception(exc)}


def add_manual_pdf_source(
    slug: str,
    file_name: str,
    file_bytes: bytes,
    title: str = "",
    mapped_section: str = "",
    reviewer_note: str = "",
    data_class: str = "public",
) -> dict[str, Any]:
    """Persist an uploaded PDF source in a review sidecar JSON file."""
    try:
        hydrate_program(slug)
        clean_data_class = str(data_class).strip().lower()
        if clean_data_class not in {"public", "internal"}:
            raise UserFacingError("Invalid data class.", "Choose public or internal.")

        clean_name = str(file_name or "").strip()
        if not clean_name:
            raise UserFacingError("A PDF filename is required.")
        if not clean_name.lower().endswith(".pdf"):
            raise UserFacingError("Only PDF files are supported for upload.")
        if not file_bytes:
            raise UserFacingError("Uploaded file is empty.")

        # Quick parse check so broken uploads are rejected immediately.
        try:
            pdf_module = __import__("pypdf")
            PdfReader = pdf_module.PdfReader
            PdfReader(BytesIO(file_bytes))
        except Exception as exc:
            raise UserFacingError("Uploaded file is not a readable PDF.", str(exc)) from exc

        review_dir = _review_dir(slug)
        review_dir.mkdir(parents=True, exist_ok=True)
        uploads_dir = review_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        safe_file_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in clean_name)
        target_path = uploads_dir / safe_file_name
        suffix = 2
        while target_path.exists():
            stem = Path(safe_file_name).stem or "source"
            ext = Path(safe_file_name).suffix or ".pdf"
            target_path = uploads_dir / f"{stem}_{suffix}{ext}"
            suffix += 1
        target_path.write_bytes(file_bytes)

        manual_path = _manual_sources_path(slug)
        manual_sources: list[dict[str, Any]] = []
        if manual_path.exists():
            manual_sources = json.loads(manual_path.read_text(encoding="utf-8"))

        name_seed = title.strip() or target_path.name
        name = _make_manual_name(slug, name_seed, str(target_path))
        existing_names = {entry.get("name", "") for entry in manual_sources}
        name_suffix = 2
        base_name = name
        while name in existing_names:
            name = f"{base_name}_{name_suffix}"
            name_suffix += 1

        sections = [mapped_section.strip()] if mapped_section.strip() else []
        review_status = "approved" if clean_data_class == "public" else "pending_manual_review"
        entry = {
            "name": name,
            "url": "",
            "file_path": str(target_path),
            "title": title.strip() or target_path.name,
            "sections": sections,
            "data_class": clean_data_class,
            "mapped_section": mapped_section.strip(),
            "note": reviewer_note.strip(),
            "source_origin": "manual_upload",
            "created_at": _utc_now(),
            "review_status": review_status,
        }
        manual_sources.append(entry)
        manual_path.write_text(json.dumps(manual_sources, indent=2), encoding="utf-8")
        storage = persist_paths(slug, ["review/manual_sources.json", f"review/uploads/{target_path.name}"])
        return {"ok": True, "entry": entry, "path": str(manual_path), "storage": storage}
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to add PDF source.", "detail": format_exception(exc)}


def load_approved_sources(slug: str) -> dict[str, Any]:
    """Return the current sources.json list for update-time editing."""
    try:
        hydrate_program(slug)
        sources = _load_sources_json(slug)
        return {
            "ok": True,
            "sources": sources,
            "path": str(_sources_path(slug)),
            "count": len(sources),
        }
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to load approved sources.", "detail": format_exception(exc)}


def add_approved_url_source(
    slug: str,
    url: str,
    title: str = "",
    sections_text: str = "",
) -> dict[str, Any]:
    """Add a public URL directly to sources.json for future updates."""
    try:
        hydrate_program(slug)
        clean_url = str(url or "").strip()
        if not clean_url:
            raise UserFacingError("URL is required.")
        try:
            clean_url = normalize_and_validate_public_url(clean_url, context="weekly update source")
        except ValueError as exc:
            raise UserFacingError("Invalid or untrusted URL.", str(exc)) from exc

        sources = _load_sources_json(slug)
        if any(str(src.get("url", "")).strip() == clean_url for src in sources):
            raise UserFacingError("That URL is already in the approved source list.")

        name = _unique_source_name(
            _make_manual_name(slug, title, clean_url),
            {str(src.get("name", "")) for src in sources},
        )
        entry = {
            "name": name,
            "url": clean_url,
            "file_path": "",
            "sections": _clean_sections(sections_text),
            "title": title.strip(),
            "data_class": "public",
            "source_origin": "weekly_update_manual",
            "created_at": _utc_now(),
        }
        sources.append(entry)
        written = _write_sources_json(slug, sources)
        return {"ok": True, "entry": entry, "count": len(sources), **written}
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to add source.", "detail": format_exception(exc)}


def add_approved_pdf_source(
    slug: str,
    file_name: str,
    file_bytes: bytes,
    title: str = "",
    sections_text: str = "",
) -> dict[str, Any]:
    """Add a public uploaded PDF directly to sources.json for future updates."""
    try:
        hydrate_program(slug)
        clean_name = str(file_name or "").strip()
        if not clean_name:
            raise UserFacingError("A PDF filename is required.")
        if not clean_name.lower().endswith(".pdf"):
            raise UserFacingError("Only PDF files are supported for upload.")
        if not file_bytes:
            raise UserFacingError("Uploaded file is empty.")

        try:
            pdf_module = __import__("pypdf")
            PdfReader = pdf_module.PdfReader
            PdfReader(BytesIO(file_bytes))
        except Exception as exc:
            raise UserFacingError("Uploaded file is not a readable PDF.", str(exc)) from exc

        sources = _load_sources_json(slug)
        review_dir = _review_dir(slug)
        uploads_dir = review_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        safe_file_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in clean_name)
        target_path = uploads_dir / safe_file_name
        suffix = 2
        while target_path.exists():
            stem = Path(safe_file_name).stem or "source"
            ext = Path(safe_file_name).suffix or ".pdf"
            target_path = uploads_dir / f"{stem}_{suffix}{ext}"
            suffix += 1
        target_path.write_bytes(file_bytes)

        name_seed = title.strip() or target_path.name
        name = _unique_source_name(
            _make_manual_name(slug, name_seed, str(target_path)),
            {str(src.get("name", "")) for src in sources},
        )
        entry = {
            "name": name,
            "url": "",
            "file_path": str(target_path),
            "sections": _clean_sections(sections_text),
            "title": title.strip() or target_path.name,
            "data_class": "public",
            "source_origin": "weekly_update_upload",
            "created_at": _utc_now(),
        }
        sources.append(entry)
        written = _write_sources_json(slug, sources)
        storage = persist_paths(slug, ["sources.json", f"review/uploads/{target_path.name}"])
        return {
            "ok": True,
            "entry": entry,
            "count": len(sources),
            "path": written["path"],
            "storage": storage,
        }
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to add PDF source.", "detail": format_exception(exc)}


def update_approved_source(
    slug: str,
    source_name: str,
    *,
    title: str = "",
    url: str = "",
    sections_text: str = "",
) -> dict[str, Any]:
    """Edit title, URL, and section mapping for one approved source."""
    try:
        hydrate_program(slug)
        sources = _load_sources_json(slug)
        target = next((src for src in sources if str(src.get("name", "")) == source_name), None)
        if target is None:
            raise UserFacingError("Selected source was not found.")

        clean_url = str(url or "").strip()
        if clean_url:
            try:
                clean_url = normalize_and_validate_public_url(clean_url, context="weekly update source")
            except ValueError as exc:
                raise UserFacingError("Invalid or untrusted URL.", str(exc)) from exc
            for src in sources:
                if src is not target and str(src.get("url", "")).strip() == clean_url:
                    raise UserFacingError("Another source already uses that URL.")
            target["url"] = clean_url
            target["file_path"] = ""
        elif not str(target.get("file_path", "")).strip():
            raise UserFacingError("URL is required for web sources.")

        target["title"] = title.strip()
        target["sections"] = _clean_sections(sections_text)
        target["data_class"] = "public"
        written = _write_sources_json(slug, sources)
        return {"ok": True, "entry": target, "count": len(sources), **written}
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to update source.", "detail": format_exception(exc)}


def remove_approved_source(slug: str, source_name: str) -> dict[str, Any]:
    """Remove one source from sources.json."""
    try:
        hydrate_program(slug)
        sources = _load_sources_json(slug)
        kept = [src for src in sources if str(src.get("name", "")) != source_name]
        if len(kept) == len(sources):
            raise UserFacingError("Selected source was not found.")
        if not kept:
            raise UserFacingError("Cannot remove the last source.", "At least one approved source is required.")
        written = _write_sources_json(slug, kept)
        return {"ok": True, "removed": source_name, "count": len(kept), **written}
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to remove source.", "detail": format_exception(exc)}


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
            metadata = {k: v for k, v in src.items() if k not in _SOURCE_BASE_FIELDS}
            rows.append(
                {
                    "name": name,
                    "url": src.get("url", ""),
                    "file_path": src.get("file_path", ""),
                    "sections": src.get("sections", []),
                    "data_class": src.get("data_class", "public"),
                    "status": decision.get("status", "unreviewed"),
                    "notes": decision.get("notes", ""),
                    "source_origin": "auto",
                    "title": src.get("title", ""),
                    "created_at": "",
                    "metadata": metadata,
                }
            )

        for src in manual_sources:
            name = src.get("name", "")
            decision = decisions.get(name, {})
            metadata = {k: v for k, v in src.items() if k not in _SOURCE_BASE_FIELDS}
            rows.append(
                {
                    "name": name,
                    "url": src.get("url", ""),
                    "file_path": src.get("file_path", ""),
                    "sections": src.get("sections", []),
                    "data_class": src.get("data_class", "public"),
                    "status": decision.get("status", src.get("review_status", "approved")),
                    "notes": decision.get("notes", src.get("note", "")),
                    "source_origin": "manual",
                    "title": src.get("title", ""),
                    "created_at": src.get("created_at", ""),
                    "metadata": metadata,
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
                data_class = str(row.get("data_class", "")).strip().lower() or "public"
                if data_class != "public":
                    raise UserFacingError(
                        "Internal sources cannot be finalized into sources.json.",
                        f"Source '{row.get('name', '')}' is marked data_class='{data_class}'.",
                    )
                approved_sources.append(
                    {
                        "name": row["name"],
                        "url": row["url"],
                        "file_path": row.get("file_path", ""),
                        "sections": row["sections"],
                        **(row.get("metadata") or {}),
                        "data_class": "public",
                    }
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
        import cite
        import scraper

        hydrate_program(slug)
        program_dir = _program_dir(slug)
        sources_path = program_dir / "sources.json"
        if not sources_path.exists():
            raise UserFacingError("No approved sources found. Finalize sources before generating first draft.")

        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        if not isinstance(sources, list) or not sources:
            raise UserFacingError("Approved sources file is empty or invalid.")
        assert_public_sources(sources, context="review first draft generation")

        guide_md = generator.generate_guide(sources, slug)
        if not isinstance(guide_md, str) or not guide_md.strip():
            raise UserFacingError(
                "Guide generation returned empty content. The LLM may have filtered the response."
            )
        missing_sections = generator.find_missing_required_sections(guide_md)
        if missing_sections:
            raise UserFacingError(
                "Generated guide is missing required sections.",
                "Missing sections: " + ", ".join(missing_sections),
            )
        guide_md = _sanitize_generated_guide_markdown(guide_md)

        evidence: list[dict] = []
        citation_count = 0
        citation_warnings: list[str] = []
        snapshot_failures: list[dict[str, str]] = []
        if not with_citations:
            citation_warnings.append("Citation generation was disabled for this run.")
        if with_citations:
            assert_public_sources(sources, context="review citation step")
            snapshot_map: dict[str, str] = {}
            source_metadata_map: dict[str, dict] = {}
            for src in sources:
                src_name = str(src.get("name", "")).strip()
                src_url = str(src.get("url", "")).strip()
                primary_error: Exception | None = None
                text = ""
                metadata: dict[str, Any] = {}
                try:
                    payload = scraper.fetch_source_payload_from_source(src)
                    if isinstance(payload, dict):
                        text = str(payload.get("text", "") or "")
                        meta = payload.get("metadata", {})
                        metadata = meta if isinstance(meta, dict) else {}
                except Exception as exc:
                    primary_error = exc
                    logger.warning(
                        "event=citation_snapshot_failed source=%s error=%s",
                        src_name,
                        exc,
                    )

                if not text and src_url:
                    try:
                        text = generator._best_effort_fetch_text(src_url)
                        if text:
                            metadata = metadata or {"extraction_method": "html_fallback"}
                            logger.info(
                                "event=citation_snapshot_fallback_ok source=%s chars=%d",
                                src_name,
                                len(text),
                            )
                    except Exception as fallback_exc:
                        logger.warning(
                            "event=citation_snapshot_fallback_failed source=%s error=%s",
                            src_name,
                            fallback_exc,
                        )
                        if primary_error is None:
                            primary_error = fallback_exc

                snapshot_map[src_name] = text
                source_metadata_map[src_name] = metadata
                if not text:
                    snapshot_failures.append(
                        {
                            "name": src_name,
                            "ref": src_url or str(src.get("file_path", "")).strip(),
                            "error": (
                                f"{type(primary_error).__name__}: {primary_error}"
                                if primary_error
                                else "empty snapshot"
                            ),
                        }
                    )

            if snapshot_failures:
                citation_warnings.append(
                    f"{len(snapshot_failures)} of {len(sources)} sources had no snapshot text "
                    "available for citation evidence."
                )

            try:
                cited_md, evidence = cite.add_citations(
                    guide_md,
                    sources=sources,
                    snapshots_by_name=snapshot_map,
                    source_metadata_by_name=source_metadata_map,
                )
                if evidence:
                    guide_md = cited_md
                    citation_count = len(evidence)
                else:
                    citation_warnings.append(
                        "Citation step completed but produced no accepted citations."
                        " Check Streamlit logs for `event=citation_skipped` for the reason."
                    )
            except SensitiveDataError:
                raise
            except Exception as exc:
                logger.warning("event=citation_step_failed error=%s", exc)
                citation_warnings.append(
                    f"Citation step failed: {type(exc).__name__}: {exc}"
                )

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
            "citation_warnings": citation_warnings,
            "snapshot_failures": snapshot_failures,
            "output_dir": str(output_dir),
            "storage": storage,
        }
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except SensitiveDataError as exc:
        error, detail = format_sensitive_data_error(exc)
        return {"ok": False, "error": error, "detail": detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to generate first draft.", "detail": format_exception(exc)}


def _write_output_files(
    guide_md: str, evidence: list[dict], output_dir: Path
) -> None:
    """Write md, docx, pdf, and evidence.json output files."""
    from src.exporters.docx_export import md_to_docx
    from src.exporters.pdf_export import md_to_pdf

    md_path = output_dir / "sponsor_guide_updated.md"
    md_path.write_text(guide_md, encoding="utf-8")

    docx_path = output_dir / "sponsor_guide_updated.docx"
    try:
        md_to_docx(guide_md, str(docx_path))
    except Exception:
        pass

    try:
        pdf_path = output_dir / "sponsor_guide_updated.pdf"
        md_to_pdf(guide_md, str(pdf_path))
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
