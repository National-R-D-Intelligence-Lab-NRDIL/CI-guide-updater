"""Human Review CLI.

Menu-driven interface for users to review, approve, reject,
edit, and **add** source links.  New links are automatically validated and
their relevant guide sections are detected by Gemini — no manual JSON
editing required.
"""

import json
import os
import re
from typing import Optional

import requests

import scraper
import updater

REVIEW_DIR = "review"


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
    print(f"\n  [{idx}/{total}]  {src['name']}")
    print(f"           URL:      {src['url']}")
    print(f"           Sections: {sec_str}")


def _print_menu() -> None:
    """Show available actions."""
    print()
    print("    1  Approve this source")
    print("    2  Reject this source")
    print("    3  Edit the URL for this source")
    print("    4  Add a new link (not in the list)")
    print("    5  Show approved sources so far")
    print("    6  Done — finish review")
    print()


def _add_new_link(
    program_prefix: str,
    guide_md: str,
) -> Optional[dict]:
    """Prompt the user for a new URL, validate it, and auto-classify sections."""
    print("\n  --- Add a new source link ---")
    url = input("  Paste the URL: ").strip()
    if not url:
        print("  (cancelled)")
        return None

    print("  Checking URL ...")
    info = _validate_url(url)
    if not info["reachable"]:
        print(f"  ✗ URL is not reachable (status {info.get('status', '?')})")
        proceed = input("  Add it anyway? (y/n): ").strip().lower()
        if proceed != "y":
            return None

    ct = info.get("content_type", "")
    if "html" not in ct and "text" not in ct:
        print(f"  ⚠  Content type is '{ct}' (not HTML). The scraper may not work on this page.")

    final_url = info.get("url", url)
    label = input("  Short label (e.g. 'Program FAQ'): ").strip() or "New_Source"
    name = _make_name(program_prefix, label)

    print("  Detecting relevant guide sections ...")
    sections: list[str] = []
    try:
        page_text = scraper.fetch_and_clean_text(final_url)
        sections = updater.classify_sections(page_text, guide_md)
    except Exception:
        pass

    if sections:
        print(f"  Auto-detected sections: {', '.join(sections)}")
    else:
        print("  Could not auto-detect sections (will be inferred at update time).")

    entry = {"name": name, "url": final_url, "sections": sections, "data_class": "public"}
    print(f"  ✓ Added: {name}")
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

    print(f"\n{'=' * 60}")
    print(f"  Source Review — {total} source(s) to review")
    print(f"{'=' * 60}")

    while idx < len(queue):
        total = len(queue)
        src = queue[idx]
        _print_source(idx + 1, total, src)
        _print_menu()

        choice = input("  Your choice (1-6): ").strip()

        if choice == "1":
            approved.append(src)
            print("  → Approved ✓")
            idx += 1

        elif choice == "2":
            print("  → Rejected")
            idx += 1

        elif choice == "3":
            new_url = input("  New URL: ").strip()
            if new_url:
                print("  Checking URL ...")
                info = _validate_url(new_url)
                final = info.get("url", new_url)
                if info["reachable"]:
                    print(f"  ✓ Reachable → {final}")
                else:
                    print(f"  ⚠ Not reachable (status {info.get('status', '?')})")
                src["url"] = final

                print("  Re-detecting sections ...")
                try:
                    page_text = scraper.fetch_and_clean_text(final)
                    src["sections"] = updater.classify_sections(page_text, guide_md)
                    if src["sections"]:
                        print(f"  Sections: {', '.join(src['sections'])}")
                except Exception:
                    pass

            approved.append(src)
            print("  → Approved (edited) ✓")
            idx += 1

        elif choice == "4":
            new_entry = _add_new_link(prefix, guide_md)
            if new_entry:
                queue.append(new_entry)
                print(f"  (Added to queue — will appear as [{len(queue)}/{len(queue)}])")

        elif choice == "5":
            if approved:
                print(f"\n  Approved so far ({len(approved)}):")
                for a in approved:
                    print(f"    • {a['name']:40s} {a['url']}")
            else:
                print("\n  No sources approved yet.")

        elif choice == "6":
            print("\n  Finishing review early.")
            break

        else:
            print("  Invalid choice — enter a number 1 through 6.")

    want_more = True
    while want_more:
        add = input("\n  Add another link before finishing? (y/n): ").strip().lower()
        if add == "y":
            new_entry = _add_new_link(prefix, guide_md)
            if new_entry:
                approved.append(new_entry)
        else:
            want_more = False

    print(f"\n  Review complete — {len(approved)} source(s) approved.")
    return approved
