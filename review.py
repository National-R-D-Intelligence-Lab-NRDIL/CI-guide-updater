"""Human Review CLI.

Menu-driven interface for users to review, approve, reject,
edit, and **add** source links.  New links are automatically validated and
their relevant guide sections are detected by Gemini — no manual JSON
editing required.
"""

import json
import logging
import os
import re
from typing import Optional

import requests

import scraper
import updater

REVIEW_DIR = "review"
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def save_for_review(
    sources: list[dict],
    guide_md: str,
    program_dir: str,
) -> tuple[str, str]:
    """Write pending sources and draft guide into the program's review folder.

    Args:
        sources: Candidate source list from :mod:`discover`.
        guide_md: Draft guide markdown from :mod:`generator`.
        program_dir: Program directory, e.g. ``programs/nsf_career``.

    Returns:
        Tuple of (sources_path, guide_path).
    """
    review_dir = os.path.join(program_dir, "review")
    os.makedirs(review_dir, exist_ok=True)

    src_path = os.path.join(review_dir, "sources_pending.json")
    with open(src_path, "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2)

    guide_path = os.path.join(review_dir, "draft_guide.md")
    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(guide_md)

    return src_path, guide_path


def finalize(
    approved: list[dict],
    guide_md: str,
    program_dir: str,
) -> tuple[str, str]:
    """Save approved sources and guide as production files inside the program dir.

    Args:
        approved: Expert-approved source list.
        guide_md: Draft (or revised) guide markdown.
        program_dir: Program directory, e.g. ``programs/nsf_career``.

    Returns:
        Tuple of (sources_json_path, guide_path).
    """
    os.makedirs(program_dir, exist_ok=True)

    sources_path = os.path.join(program_dir, "sources.json")
    with open(sources_path, "w", encoding="utf-8") as f:
        json.dump(approved, f, indent=2)

    guide_path = os.path.join(program_dir, "guide.md")
    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(guide_md)

    return sources_path, guide_path


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _make_name(prefix: str, label: str) -> str:
    """Build a safe snapshot ID from a prefix and a label."""
    raw = f"{prefix}_{label}"
    return re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")


def _validate_url(url: str) -> dict:
    """Quick-check a URL and return status info."""
    info: dict = {"url": url, "reachable": False, "content_type": ""}
    try:
        r = requests.get(url, timeout=15, allow_redirects=True, stream=True)
        r.close()
        info["status"] = r.status_code
        info["content_type"] = r.headers.get("content-type", "").split(";")[0].strip()
        info["reachable"] = r.status_code == 200
        if r.url != url:
            info["url"] = r.url
    except Exception as exc:
        info["error"] = str(exc)
    return info


# ---------------------------------------------------------------------------
# Interactive review
# ---------------------------------------------------------------------------

def _print_source(idx: int, total: int, src: dict) -> None:
    """Pretty-print one source entry."""
    sections = src.get("sections", [])
    sec_str = ", ".join(sections) if sections else "(auto-detect on next pipeline run)"
    logger.info("review_source index=%d total=%d name=%s", idx, total, src["name"])
    logger.info("review_source_url name=%s url=%s", src["name"], src["url"])
    logger.info("review_source_sections name=%s sections=%s", src["name"], sec_str)


def _print_menu() -> None:
    """Show available actions."""
    logger.info("review_menu options=1:approve,2:reject,3:edit_url,4:add_link,5:show_approved,6:finish")


def _add_new_link(
    program_prefix: str,
    guide_md: str,
) -> Optional[dict]:
    """Prompt the user for a new URL, validate it, and auto-classify sections."""
    logger.info("review_add_link status=start")
    url = input("  Paste the URL: ").strip()
    if not url:
        logger.info("review_add_link status=cancelled reason=empty_url")
        return None

    logger.info("review_add_link status=validating_url")
    info = _validate_url(url)
    if not info["reachable"]:
        logger.warning("review_add_link url_reachable=false status=%s", info.get("status", "?"))
        proceed = input("  Add it anyway? (y/n): ").strip().lower()
        if proceed != "y":
            return None

    ct = info.get("content_type", "")
    if "html" not in ct and "text" not in ct:
        logger.warning("review_add_link content_type=%s warning=non_html", ct)

    final_url = info.get("url", url)
    label = input("  Short label (e.g. 'Program FAQ'): ").strip() or "New_Source"
    name = _make_name(program_prefix, label)

    logger.info("review_add_link status=detecting_sections")
    sections: list[str] = []
    try:
        page_text = scraper.fetch_and_clean_text(final_url)
        sections = updater.classify_sections(page_text, guide_md)
    except Exception:
        pass

    if sections:
        logger.info("review_add_link autodetected_sections=%s", ",".join(sections))
    else:
        logger.info("review_add_link autodetected_sections=none")

    entry = {"name": name, "url": final_url, "sections": sections, "data_class": "public"}
    logger.info("review_add_link status=added name=%s url=%s", name, final_url)
    return entry


def interactive_review(
    sources: list[dict],
    program: str = "",
    guide_md: str = "",
) -> list[dict]:
    """Walk the expert through each source for approval.

    Uses a numbered menu so users can participate easily.
    Supports adding new links at any point during the review.

    Args:
        sources: Candidate source list.
        program: Program name (used as prefix for new source IDs).
        guide_md: Current guide markdown (used for auto-section detection).

    Returns:
        List of approved (possibly edited/extended) sources.
    """
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", program).strip("_") or "Source"
    approved: list[dict] = []
    queue = list(sources)
    idx = 0
    total = len(queue)

    logger.info("review_start total_sources=%d", total)

    while idx < len(queue):
        total = len(queue)
        src = queue[idx]
        _print_source(idx + 1, total, src)
        _print_menu()

        choice = input("  Your choice (1-6): ").strip()

        if choice == "1":
            approved.append(src)
            logger.info("review_action action=approve name=%s", src["name"])
            idx += 1

        elif choice == "2":
            logger.info("review_action action=reject name=%s", src["name"])
            idx += 1

        elif choice == "3":
            new_url = input("  New URL: ").strip()
            if new_url:
                logger.info("review_action action=edit_url_validate name=%s", src["name"])
                info = _validate_url(new_url)
                final = info.get("url", new_url)
                if info["reachable"]:
                    logger.info("review_action action=edit_url_reachable name=%s url=%s", src["name"], final)
                else:
                    logger.warning(
                        "review_action action=edit_url_unreachable name=%s status=%s",
                        src["name"],
                        info.get("status", "?"),
                    )
                src["url"] = final

                logger.info("review_action action=edit_url_redetect_sections name=%s", src["name"])
                try:
                    page_text = scraper.fetch_and_clean_text(final)
                    src["sections"] = updater.classify_sections(page_text, guide_md)
                    if src["sections"]:
                        logger.info(
                            "review_action action=edit_url_sections name=%s sections=%s",
                            src["name"],
                            ",".join(src["sections"]),
                        )
                except Exception:
                    pass

            approved.append(src)
            logger.info("review_action action=approve_edited name=%s", src["name"])
            idx += 1

        elif choice == "4":
            new_entry = _add_new_link(prefix, guide_md)
            if new_entry:
                queue.append(new_entry)
                logger.info("review_action action=queued_new_source position=%d", len(queue))

        elif choice == "5":
            if approved:
                logger.info("review_action action=show_approved count=%d", len(approved))
                for a in approved:
                    logger.info("review_approved_item name=%s url=%s", a["name"], a["url"])
            else:
                logger.info("review_action action=show_approved count=0")

        elif choice == "6":
            logger.info("review_action action=finish_early")
            break

        else:
            logger.warning("review_action action=invalid_choice value=%s", choice)

    want_more = True
    while want_more:
        add = input("\n  Add another link before finishing? (y/n): ").strip().lower()
        if add == "y":
            new_entry = _add_new_link(prefix, guide_md)
            if new_entry:
                approved.append(new_entry)
        else:
            want_more = False

    logger.info("review_complete approved_count=%d", len(approved))
    return approved
