"""Services for audit/evidence traceability views."""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from src.utils.errors import format_exception


_CITATION_RE = re.compile(r"\[(?:\[(\d+)\]|(\d+))\]\((https?://[^)\s]+)\)")


def load_audit_data(program_slug: str) -> dict[str, Any]:
    """Load guide diffs, citation links, and evidence map for one program."""
    try:
        program_dir = Path("programs") / program_slug
        baseline_path = program_dir / "guide.md"
        updated_path = program_dir / "output" / "sponsor_guide_updated.md"
        evidence_path = program_dir / "output" / "sponsor_guide_evidence.json"

        baseline_text = baseline_path.read_text(encoding="utf-8") if baseline_path.exists() else ""
        updated_text = updated_path.read_text(encoding="utf-8") if updated_path.exists() else ""

        diff_lines = list(
            difflib.unified_diff(
                baseline_text.splitlines(),
                updated_text.splitlines(),
                fromfile=str(baseline_path),
                tofile=str(updated_path),
                lineterm="",
            )
        )
        diff_text = "\n".join(diff_lines) if diff_lines else ""

        citations = []
        for match in _CITATION_RE.finditer(updated_text):
            citation_id = match.group(1) or match.group(2) or "?"
            citations.append({"id": citation_id, "url": match.group(3)})

        evidence = []
        if evidence_path.exists():
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        return {
            "ok": True,
            "program_slug": program_slug,
            "diff_text": diff_text,
            "citations": citations,
            "evidence": evidence,
            "baseline_path": str(baseline_path),
            "updated_path": str(updated_path),
            "evidence_path": str(evidence_path),
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "Failed to load audit artifacts.", "detail": format_exception(exc)}
