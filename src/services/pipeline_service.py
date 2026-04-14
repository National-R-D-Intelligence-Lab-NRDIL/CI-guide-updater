"""Service wrapper for weekly pipeline execution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pipeline
from src.services.persistence_service import hydrate_program, persist_program
from src.utils.errors import UserFacingError, format_exception
from src.utils.logging_utils import capture_logs


def _resolve_default_guide(program_dir: Path) -> Path:
    guide_md = program_dir / "guide.md"
    if guide_md.exists():
        return guide_md
    raise UserFacingError(
        "Baseline guide.md not found. In Review Sources, generate the first draft and promote it to baseline first."
    )


def run_weekly_update(
    program_slug: str,
    *,
    with_citations: bool = True,
    refresh_citations: bool = False,
    refresh_citations_only: bool = False,
) -> dict[str, Any]:
    """Run existing pipeline for a program and return UI-friendly summary data."""
    try:
        hydrate_program(program_slug)
        program_dir = Path("programs") / program_slug
        sources_path = program_dir / "sources.json"
        if not sources_path.exists():
            raise UserFacingError("Approved sources not found for selected program.")
        guide_path = _resolve_default_guide(program_dir)

        output_dir = program_dir / "output"
        state_file = program_dir / "state.json"
        data_dir = program_dir / "data"

        def _run() -> bool:
            return pipeline.run_pipeline(
                sources_config=str(sources_path),
                guide_path=str(guide_path),
                output_dir=str(output_dir),
                state_file=str(state_file),
                data_dir=str(data_dir),
                with_citations=with_citations,
                refresh_citations=refresh_citations,
                refresh_citations_only=refresh_citations_only,
            )

        ok, logs = capture_logs(_run)

        changed_sources = re.findall(r"✓\s+(.+?): changes detected", logs)
        auto_section_lines = re.findall(r"auto-detected sections → (.+)", logs)
        changed_sections = 0
        for item in auto_section_lines:
            changed_sections += len([s for s in item.split(",") if s.strip()])

        artifacts = []
        for name in [
            "sponsor_guide_updated.md",
            "sponsor_guide_updated.docx",
            "sponsor_guide_updated.pdf",
            "sponsor_guide_evidence.json",
        ]:
            path = output_dir / name
            if path.exists():
                artifacts.append(str(path))

        storage = persist_program(program_slug)
        return {
            "ok": True,
            "updated": bool(ok),
            "program_slug": program_slug,
            "sources_path": str(sources_path),
            "guide_path": str(guide_path),
            "output_dir": str(output_dir),
            "changed_sources_count": len(changed_sources),
            "changed_sources": changed_sources,
            "changed_sections_count": changed_sections,
            "artifacts": artifacts,
            "logs": logs,
            "storage": storage,
        }
    except UserFacingError as exc:
        return {"ok": False, "error": exc.message, "detail": exc.detail}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Weekly update failed.", "detail": format_exception(exc)}
