"""Service wrapper for non-interactive program bootstrap flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import discover
import notify_review
import review_async
from program_utils import make_slug
from src.utils.errors import UserFacingError, format_exception
from src.utils.validation import ensure_path_exists, require_non_empty


def create_new_program(
    program: str,
    *,
    async_review: bool = False,
    shared_review_dir: str = "",
    notify_webhook_url: str = "",
) -> dict[str, Any]:
    """Create initial review workspace for a new program.

    This wraps the same underlying functions used by `bootstrap.py` while avoiding
    interactive prompts and process termination behavior.
    """
    try:
        program_name = require_non_empty(program, "Program name")
        slug = make_slug(program_name)
        program_dir = Path("programs") / slug
        program_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = program_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "program": program_name,
                    "slug": slug,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        candidates = discover.discover_sources(program_name)
        validated_candidates = discover.validate_urls(candidates)
        sources = discover.build_sources_json(program_name, validated_candidates)
        if not sources:
            raise UserFacingError("No scrapeable sources discovered for this program.")

        review_dir = program_dir / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        sources_pending_path = review_dir / "sources_pending.json"
        sources_pending_path.write_text(json.dumps(sources, indent=2), encoding="utf-8")

        created_files = [str(metadata_path), str(sources_pending_path)]
        next_steps = [
            f"Continue to review candidate sources.",
            "Finalize approved sources in the Review Sources page.",
        ]

        async_details: dict[str, str] = {}
        if async_review:
            shared_dir = ensure_path_exists(shared_review_dir, "Shared review directory")
            review_id, package_dir = review_async.create_review_package(
                program=program_name,
                program_slug=slug,
                program_dir=str(program_dir),
                sources=sources,
                guide_md="",
            )
            published_dir = review_async.publish_review_package(
                package_dir=package_dir,
                shared_review_dir=str(shared_dir),
                program_slug=slug,
                review_id=review_id,
            )
            webhook_sent = False
            webhook_error = ""
            if notify_webhook_url.strip():
                collect_cmd = (
                    "python3 collect_review.py "
                    f"\"{program_name}\" --shared-review-dir \"{shared_dir}\" "
                    f"--review-id {review_id}"
                )
                message = notify_review.build_async_review_message(
                    program=program_name,
                    review_id=review_id,
                    shared_dir=published_dir,
                    collect_cmd=collect_cmd,
                )
                webhook_error = notify_review.send_webhook_message(notify_webhook_url, message) or ""
                webhook_sent = webhook_error == ""
            async_details = {
                "review_id": review_id,
                "local_package_dir": package_dir,
                "shared_package_dir": published_dir,
                "notify_webhook_configured": "yes" if notify_webhook_url.strip() else "no",
                "webhook_sent": "yes" if webhook_sent else "no",
                "webhook_error": webhook_error,
            }
            created_files.extend([package_dir, published_dir])
            next_steps.append("After reviewer approval, run collect_review.py to finalize.")
        else:
            next_steps.append("After approval, generate the first draft from approved sources.")

        return {
            "ok": True,
            "program": program_name,
            "program_display_name": program_name,
            "slug": slug,
            "program_dir": str(program_dir),
            "candidate_count": len(validated_candidates),
            "reachable_count": sum(1 for c in validated_candidates if c.get("reachable")),
            "source_count": len(sources),
            "created_files": created_files,
            "next_steps": next_steps,
            "candidates": validated_candidates,
            "async_details": async_details,
        }
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover - defensive error boundary
        return {
            "ok": False,
            "error": "Program bootstrap failed.",
            "detail": format_exception(exc),
        }
