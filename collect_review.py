"""Collect approved async-review files from a shared folder.

Use after bootstrap async mode:
    python3 bootstrap.py "NSF CAREER award" --async-review --shared-review-dir "/path/to/shared"

Then experts edit shared files and set manifest status to "approved".
This script pulls the latest files and finalizes:
    python3 collect_review.py "NSF CAREER award" --shared-review-dir "/path/to/shared"
"""

import argparse
import json
import os
import time
from typing import Optional

import review
import review_async
from program_utils import make_slug


_APPROVED_STATES = {"approved", "done", "ready"}


def _sync_local_review_copy(program_dir: str, sources: list[dict], guide_md: str) -> None:
    """Update local review/ copy with the collected shared edits."""
    review_dir = os.path.join(program_dir, "review")
    os.makedirs(review_dir, exist_ok=True)

    with open(os.path.join(review_dir, "sources_pending.json"), "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2)

    with open(os.path.join(review_dir, "draft_guide.md"), "w", encoding="utf-8") as f:
        f.write(guide_md)


def collect_once(
    program: str,
    shared_review_dir: str,
    review_id: Optional[str] = None,
    require_approved: bool = True,
) -> tuple[bool, str]:
    """Collect one review package.

    Returns:
        (done, message)
        - done=True when files were collected and finalized.
        - done=False when waiting for approval or package is missing.
    """
    slug = make_slug(program)
    program_dir = os.path.join("programs", slug)
    os.makedirs(program_dir, exist_ok=True)

    effective_id = review_id or review_async.latest_review_id(shared_review_dir, slug)
    if not effective_id:
        return False, f"No review package found in shared folder for '{slug}'."

    shared_pkg = review_async.get_shared_package_dir(shared_review_dir, slug, effective_id)
    if not os.path.isdir(shared_pkg):
        return False, f"Shared package does not exist: {shared_pkg}"

    try:
        manifest = review_async.load_manifest(shared_pkg)
    except FileNotFoundError:
        return False, f"manifest.json not found in shared package: {shared_pkg}"

    status = str(manifest.get("status", "")).strip().lower()
    if require_approved and status not in _APPROVED_STATES:
        return (
            False,
            f"Review not approved yet (status='{status or 'missing'}'). "
            "Waiting for status=approved.",
        )

    try:
        sources, guide_md = review_async.load_review_outputs(shared_pkg)
    except Exception as exc:
        return False, f"Failed to parse reviewed files: {exc}"

    _sync_local_review_copy(program_dir, sources, guide_md)
    sources_out, guide_out = review.finalize(sources, guide_md, program_dir)
    return True, (
        "Collected approved review successfully.\n"
        f"  Approved sources : {sources_out}\n"
        f"  Baseline guide   : {guide_out}\n"
        f"  Weekly run       : python3 pipeline.py {guide_out} --sources {sources_out}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect approved async review files from shared folder.",
    )
    parser.add_argument("program", help='Grant program name, e.g. "NSF CAREER award"')
    parser.add_argument(
        "--shared-review-dir",
        required=True,
        help="Shared folder path where async review packages are published.",
    )
    parser.add_argument(
        "--review-id",
        default=None,
        help="Specific review ID (default: latest package in shared folder).",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Poll shared package until approved, then collect automatically.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        help="Polling interval for --watch mode (default: 300).",
    )
    parser.add_argument(
        "--allow-unapproved",
        action="store_true",
        help="Collect even if manifest status is not approved.",
    )
    args = parser.parse_args()

    if not args.watch:
        done, message = collect_once(
            program=args.program,
            shared_review_dir=args.shared_review_dir,
            review_id=args.review_id,
            require_approved=not args.allow_unapproved,
        )
        print(message)
        if not done:
            raise SystemExit(1)
        return

    print("Watching shared review package ...")
    while True:
        done, message = collect_once(
            program=args.program,
            shared_review_dir=args.shared_review_dir,
            review_id=args.review_id,
            require_approved=not args.allow_unapproved,
        )
        print(message)
        if done:
            return
        time.sleep(max(5, args.interval_seconds))


if __name__ == "__main__":
    main()
