"""Bootstrap orchestrator.

Full flow for a new grant program:

    discover → scrape + generate → human review → finalize

All output goes into ``programs/<slug>/``.

Usage:
    python3 bootstrap.py "NSF CAREER award"
"""

import argparse
import logging
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
from src.utils.logging_utils import configure_rotating_file_logging

_PROJECT_ROOT = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


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
    logger.info("bootstrap_start program=%s output_dir=%s", program, f"{program_dir}/")
    logger.info("step=1 action=discover_sources status=start")
    candidates = discover.discover_sources(program)
    logger.info("step=1 action=discover_sources status=done candidates=%d", len(candidates))

    # -- 2. Validate -----------------------------------------------------------
    logger.info("step=2 action=validate_urls status=start")
    candidates = discover.validate_urls(candidates)
    reachable = [c for c in candidates if c.get("reachable")]
    html_only = [
        c for c in reachable
        if "html" in c.get("content_type", "") or "text" in c.get("content_type", "")
    ]
    logger.info(
        "step=2 action=validate_urls status=done reachable=%d scrapeable_html=%d",
        len(reachable),
        len(html_only),
    )
    for c in candidates:
        ok = "✓" if c.get("reachable") else "✗"
        logger.info("step=2 candidate_status=%s label=%s url=%s", ok, c["label"], c["url"])

    sources = discover.build_sources_json(program, candidates)
    if not sources:
        logger.error("bootstrap_failed reason=no_scrapeable_sources")
        sys.exit(1)

    # -- 3. Generate draft guide -----------------------------------------------
    logger.info("step=3 action=generate_guide status=start sources=%d", len(sources))
    guide_md = generator.generate_guide(sources, program)
    logger.info("step=3 action=generate_guide status=done guide_chars=%d", len(guide_md))

    src_path, guide_path = review.save_for_review(sources, guide_md, program_dir)
    logger.info("step=3 action=save_review_files status=done sources_path=%s guide_path=%s", src_path, guide_path)

    # -- 4. Human review -------------------------------------------------------
    if async_review:
        logger.info("step=4 action=prepare_async_review status=start")
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
        logger.info(
            "step=4 action=prepare_async_review status=done program_dir=%s review_id=%s local_package=%s shared_package=%s",
            f"{program_dir}/",
            review_id,
            package_dir,
            shared_dir,
        )
        collect_cmd = (
            "python3 collect_review.py "
            f"\"{program}\" --shared-review-dir \"{shared_review_dir}\" "
            f"--review-id {review_id}"
        )
        logger.info("async_review_collect_command=%s", collect_cmd)

        if notify_webhook_url:
            message = notify_review.build_async_review_message(
                program=program,
                review_id=review_id,
                shared_dir=shared_dir,
                collect_cmd=collect_cmd,
            )
            error = notify_review.send_webhook_message(notify_webhook_url, message)
            if error:
                logger.warning("async_review_notification status=failed error=%s", error)
            else:
                logger.info("async_review_notification status=sent")
        return

    if skip_review:
        logger.info("step=4 action=review status=skipped reason=skip_review")
        approved = sources
    else:
        logger.info("step=4 action=review status=start mode=interactive")
        approved = review.interactive_review(sources, program=program, guide_md=guide_md)

    if not approved:
        logger.info("result=no_sources_approved")
        return

    sources_out, guide_out = review.finalize(approved, guide_md, program_dir)
    logger.info(
        "bootstrap_complete program_dir=%s sources_path=%s guide_path=%s approved_count=%d",
        f"{program_dir}/",
        sources_out,
        guide_out,
        len(approved),
    )
    logger.info("next_command=python3 pipeline.py %s --sources %s", guide_out, sources_out)


def main() -> None:
    load_dotenv(_PROJECT_ROOT / ".env")
    configure_rotating_file_logging(log_file=Path("logs") / "bootstrap.log")
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
