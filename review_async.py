"""Asynchronous human-review helpers using a shared folder.

This module supports a lightweight collaboration flow:
1) Create a review package from discovered sources + draft guide.
2) Publish that package to a shared folder (OneDrive/SharePoint synced path).
3) Collect approved files back into the local program folder.
"""

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from src.utils.source_policy import assert_public_sources


def _utc_now() -> str:
    """Return an ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_review_id() -> str:
    """Create a lexicographically sortable review package ID."""
    return datetime.now(timezone.utc).strftime("r%Y%m%d_%H%M%S")


def create_review_package(
    program: str,
    program_slug: str,
    program_dir: str,
    sources: list[dict],
    guide_md: str,
    review_id: Optional[str] = None,
) -> tuple[str, str]:
    """Create a local review package under programs/<slug>/review_packages/<id>.

    Returns:
        Tuple of (review_id, package_dir).
    """
    review_id = review_id or make_review_id()
    package_dir = os.path.join(program_dir, "review_packages", review_id)
    os.makedirs(package_dir, exist_ok=True)

    sources_path = os.path.join(package_dir, "sources_pending.json")
    guide_path = os.path.join(package_dir, "draft_guide.md")
    manifest_path = os.path.join(package_dir, "manifest.json")

    with open(sources_path, "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2)

    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(guide_md)

    manifest = {
        "program": program,
        "program_slug": program_slug,
        "review_id": review_id,
        "created_at": _utc_now(),
        "status": "pending_review",
        "instructions": (
            "Experts should edit sources_pending.json and draft_guide.md, "
            "then set status to approved in this manifest."
        ),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return review_id, package_dir


def publish_review_package(
    package_dir: str,
    shared_review_dir: str,
    program_slug: str,
    review_id: str,
) -> str:
    """Publish a local package to a shared folder and return destination path."""
    dest_dir = os.path.join(shared_review_dir, program_slug, review_id)
    os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    shutil.copytree(package_dir, dest_dir)
    return dest_dir


def get_shared_package_dir(
    shared_review_dir: str,
    program_slug: str,
    review_id: str,
) -> str:
    """Build the shared package path."""
    return os.path.join(shared_review_dir, program_slug, review_id)


def latest_review_id(shared_review_dir: str, program_slug: str) -> Optional[str]:
    """Return the latest review ID found in shared folder for a program."""
    root = os.path.join(shared_review_dir, program_slug)
    if not os.path.isdir(root):
        return None
    ids = [name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name))]
    if not ids:
        return None
    ids.sort()
    return ids[-1]


def load_manifest(shared_package_dir: str) -> dict:
    """Read manifest.json from the shared package."""
    path = os.path.join(shared_package_dir, "manifest.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_review_outputs(shared_package_dir: str) -> tuple[list[dict], str]:
    """Read edited source list and guide markdown from the shared package."""
    src_path = os.path.join(shared_package_dir, "sources_pending.json")
    guide_path = os.path.join(shared_package_dir, "draft_guide.md")

    with open(src_path, "r", encoding="utf-8") as f:
        sources = json.load(f)
    with open(guide_path, "r", encoding="utf-8") as f:
        guide_md = f.read()

    if not isinstance(sources, list):
        raise ValueError("sources_pending.json must be a JSON array")
    for idx, src in enumerate(sources):
        if not isinstance(src, dict):
            raise ValueError(f"Source at index {idx} must be an object")
        if not src.get("name") or not src.get("url"):
            raise ValueError(
                f"Source at index {idx} must include non-empty 'name' and 'url'"
            )
        if "sections" not in src:
            src["sections"] = []

    assert_public_sources(sources, context="review package loading")

    return sources, guide_md
