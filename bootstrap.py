"""Bootstrap orchestrator.

Full flow for a new grant program:

    discover → scrape + generate → human review → finalize

All output goes into ``programs/<slug>/``.

Usage:
    python3 bootstrap.py "NSF CAREER award"
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import discover
import generator
import notify_review
from program_utils import make_slug
import review
import review_async

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")


def run_bootstrap(
    program: str,
    skip_review: bool = False,
    async_review: bool = False,
    shared_review_dir: str = "",
    notify_webhook_url: str = "",
) -> None:
    """Execute the full bootstrap pipeline for a new program.

    Args:
        program: Grant program name, e.g. ``"NSF CAREER award"``.
        skip_review: If True, auto-approve all reachable sources
            (useful for testing).
    """
    slug = make_slug(program)
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
    if async_review:
        print("[4/4] Preparing async review package ...")
        review_id, package_dir = review_async.create_review_package(
            program=program,
            program_slug=slug,
            program_dir=program_dir,
            sources=sources,
            guide_md=guide_md,
        )
        shared_dir = review_async.publish_review_package(
            package_dir=package_dir,
            shared_review_dir=shared_review_dir,
            program_slug=slug,
            review_id=review_id,
        )
        print("\n" + "=" * 60)
        print("  Async review package published")
        print("=" * 60)
        print(f"  Program folder   : {program_dir}/")
        print(f"  Review ID        : {review_id}")
        print(f"  Local package    : {package_dir}")
        print(f"  Shared package   : {shared_dir}")
        print()
        print("  Expert actions:")
        print("    1) Edit sources_pending.json and draft_guide.md")
        print("    2) Set manifest.json status to \"approved\"")
        print()
        print("  Then collect approved edits with:")
        collect_cmd = (
            "python3 collect_review.py "
            f"\"{program}\" --shared-review-dir \"{shared_review_dir}\" "
            f"--review-id {review_id}"
        )
        print(f"    {collect_cmd}")
        print()

        if notify_webhook_url:
            message = notify_review.build_async_review_message(
                program=program,
                review_id=review_id,
                shared_dir=shared_dir,
                collect_cmd=collect_cmd,
            )
            error = notify_review.send_webhook_message(notify_webhook_url, message)
            if error:
                print(f"  [warn] Notification failed: {error}")
            else:
                print("  ✓ Notification sent to webhook")
                print()
        return

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
    parser.add_argument(
        "--async-review",
        action="store_true",
        help="Publish review package to shared folder and exit.",
    )
    parser.add_argument(
        "--shared-review-dir",
        default="",
        help="Shared folder path for async review packages.",
    )
    parser.add_argument(
        "--notify-webhook-url",
        default=os.getenv("REVIEW_NOTIFY_WEBHOOK_URL", ""),
        help=(
            "Optional Teams/generic webhook URL for async-review notifications. "
            "Defaults to REVIEW_NOTIFY_WEBHOOK_URL from environment."
        ),
    )
    args = parser.parse_args()
    if args.async_review and not args.shared_review_dir:
        parser.error("--shared-review-dir is required with --async-review")
    run_bootstrap(
        args.program,
        skip_review=args.skip_review,
        async_review=args.async_review,
        shared_review_dir=args.shared_review_dir,
        notify_webhook_url=args.notify_webhook_url,
    )


if __name__ == "__main__":
    main()
