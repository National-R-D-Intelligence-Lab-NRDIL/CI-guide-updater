"""Services for output artifact discovery and preview."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.services.persistence_service import hydrate_program, program_remote_url
from src.utils.errors import format_exception


def _metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def load_outputs(program_slug: str) -> dict[str, Any]:
    """Load output artifact metadata and markdown preview content for a program."""
    try:
        hydrate_program(program_slug)
        program_dir = Path("programs") / program_slug
        output_dir = program_dir / "output"
        baseline_path = program_dir / "guide.md"
        draft_path = program_dir / "review" / "draft_guide.md"
        if not output_dir.exists():
            markdown_content = ""
            note = "No output files yet. Generate the first draft in Review Sources."
            if baseline_path.exists():
                markdown_content = baseline_path.read_text(encoding="utf-8")
                note = "Showing baseline guide. Run Weekly Update for incremental updates."
            elif draft_path.exists():
                markdown_content = draft_path.read_text(encoding="utf-8")
                note = "Showing draft guide. Promote to baseline or run Weekly Update for output artifacts."
            return {
                "ok": True,
                "program_slug": program_slug,
                "output_dir": str(output_dir),
                "artifacts": [],
                "markdown_content": markdown_content,
                "note": note,
                "baseline_path": str(baseline_path) if baseline_path.exists() else "",
                "draft_path": str(draft_path) if draft_path.exists() else "",
                "remote_program_url": program_remote_url(program_slug),
            }

        artifacts = []
        for name in [
            "sponsor_guide_updated.md",
            "sponsor_guide_updated.docx",
            "sponsor_guide_updated.pdf",
            "sponsor_guide_evidence.json",
        ]:
            path = output_dir / name
            if path.exists():
                artifacts.append(_metadata(path))

        latest_md_path = output_dir / "sponsor_guide_updated.md"
        baseline_md_path = program_dir / "guide.md"
        markdown_content = ""
        if latest_md_path.exists():
            markdown_content = latest_md_path.read_text(encoding="utf-8")
        elif baseline_md_path.exists():
            markdown_content = baseline_md_path.read_text(encoding="utf-8")

        return {
            "ok": True,
            "program_slug": program_slug,
            "output_dir": str(output_dir),
            "artifacts": artifacts,
            "markdown_content": markdown_content,
            "note": "",
            "baseline_path": str(baseline_path) if baseline_path.exists() else "",
            "draft_path": str(draft_path) if draft_path.exists() else "",
            "remote_program_url": program_remote_url(program_slug),
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to load outputs.", "detail": format_exception(exc)}


def read_artifact_bytes(path_str: str) -> bytes:
    """Read binary bytes for download button payloads."""
    return Path(path_str).read_bytes()
