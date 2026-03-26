"""Bootstrap orchestrator.

Full flow for a new grant program:

    discover → scrape + generate → human review → finalize

All output goes into ``programs/<slug>/``.

Usage:
    python3 bootstrap.py "NSF CAREER award"
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

import discover
import generator
import review

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")


def _make_slug(program: str) -> str:
    """Convert a program name to a clean, short directory slug.

    Examples:
        "NSF CAREER award"  →  "nsf_career_award"
        "NSF Faculty Early Career Development (CAREER) Program"
            →  "nsf_faculty_early_career_development_career_program"
    """
    slug = program.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def run_bootstrap(program: str, skip_review: bool = False) -> None:
    """Execute the full bootstrap pipeline for a new program.

    Args:
        program: Grant program name, e.g. ``"NSF CAREER award"``.
        skip_review: If True, auto-approve all reachable sources
            (useful for testing).
    """
    slug = _make_slug(program)
    program_dir = os.path.join("programs", slug)
    os.makedirs(program_dir, exist_ok=True)

    # -- 1. Discover -----------------------------------------------------------
    print("=" * 60)
    print(f"  Bootstrapping: {program}")
    print(f"  Output folder: {program_dir}/")
    print("=" * 60)
    print()
    print("[1/4] Discovering sources via Gemini + Google Search ...")
    candidates = discover.discover_sources(program)
    print(f"       Found {len(candidates)} candidate URL(s)\n")

    # -- 2. Validate -----------------------------------------------------------
    print("[2/4] Validating URLs ...")
    candidates = discover.validate_urls(candidates)
    reachable = [c for c in candidates if c.get("reachable")]
    html_only = [
        c for c in reachable
        if "html" in c.get("content_type", "") or "text" in c.get("content_type", "")
    ]
    print(f"       {len(reachable)} reachable, {len(html_only)} scrapeable HTML pages")
    for c in candidates:
        ok = "✓" if c.get("reachable") else "✗"
        print(f"       {ok}  {c['label']:30s}  {c['url']}")
    print()

    sources = discover.build_sources_json(program, candidates)
    if not sources:
        print("[error] No scrapeable sources found. Exiting.")
        sys.exit(1)

    # -- 3. Generate draft guide -----------------------------------------------
    print(f"[3/4] Generating draft Sponsor Guide ({len(sources)} sources) ...")
    guide_md = generator.generate_guide(sources, program)
    print(f"       Draft guide: {len(guide_md)} chars\n")

    src_path, guide_path = review.save_for_review(sources, guide_md, program_dir)
    print(f"       Review files saved:")
    print(f"         Sources → {src_path}")
    print(f"         Guide   → {guide_path}\n")

    # -- 4. Human review -------------------------------------------------------
    if skip_review:
        print("[4/4] Skipping review (--skip-review). Auto-approving all sources.")
        approved = sources
    else:
        print("[4/4] Human review ...")
        approved = review.interactive_review(sources, program=program, guide_md=guide_md)

    if not approved:
        print("\n[result] No sources approved. Nothing to save.")
        return

    sources_out, guide_out = review.finalize(approved, guide_md, program_dir)
    print(f"\n{'=' * 60}")
    print(f"  Bootstrap complete!")
    print(f"{'=' * 60}")
    print(f"  Program folder   : {program_dir}/")
    print(f"  Approved sources : {sources_out}  ({len(approved)} entries)")
    print(f"  Baseline guide   : {guide_out}")
    print()
    print(f"  To run the weekly update pipeline:")
    print(f"    python3 pipeline.py {guide_out} --sources {sources_out}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap a new grant program: discover sources, "
        "generate guide, review, finalize.",
    )
    parser.add_argument(
        "program",
        help='Grant program name, e.g. "NSF CAREER award"',
    )
    parser.add_argument(
        "--skip-review",
        action="store_true",
        help="Auto-approve all sources (skip interactive review)",
    )
    args = parser.parse_args()
    run_bootstrap(args.program, args.skip_review)


if __name__ == "__main__":
    main()
