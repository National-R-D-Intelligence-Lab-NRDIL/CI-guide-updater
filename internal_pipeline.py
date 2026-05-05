"""Internal data pipeline — template substitution only, no LLM rewriting.

This pipeline handles internal/confidential data that must never leave the
institution. It uses only local template substitution to produce guide sections,
ensuring no data is sent to any external LLM endpoint.

Usage:
    python internal_pipeline.py guide.md --sources internal_sources.json

The sources JSON must include entries with data_class="internal". Each entry
should include a "template_fields" dict with key-value pairs for substitution.
"""

import argparse
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Optional

from src.utils.logging_utils import configure_rotating_file_logging

logger = logging.getLogger(__name__)

_DEFAULT_SECTION_TEMPLATE = """\
## ${section_title}

${content}

*Source: ${source_name} (internal, last updated ${last_updated})*
"""

_FULL_GUIDE_WRAPPER = """\
# ${program_name} — Internal Supplement

> This document was generated from internal data using template substitution only.
> No content was sent to an external LLM.

Generated: ${generated_at}

---

${sections}
"""


def load_internal_sources(config_path: str) -> list[dict]:
    """Load internal source definitions from a JSON config file.

    Each source must have data_class="internal" and a template_fields dict.

    Raises:
        ValueError: If any source is missing required fields or has
            data_class != "internal".
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        sources = json.load(fh)

    if not isinstance(sources, list):
        raise ValueError("Internal sources config must be a JSON array.")

    for idx, src in enumerate(sources):
        if not isinstance(src, dict):
            raise ValueError(f"Source at index {idx} must be an object.")

        name = str(src.get("name", "")).strip()
        if not name:
            raise ValueError(f"Source at index {idx} must include a non-empty 'name'.")

        data_class = str(src.get("data_class", "")).strip().lower()
        if data_class != "internal":
            raise ValueError(
                f"Source '{name}' at index {idx} has data_class='{data_class}'. "
                "Only data_class='internal' is allowed in the internal pipeline."
            )

        template_fields = src.get("template_fields")
        if not isinstance(template_fields, dict):
            raise ValueError(
                f"Source '{name}' at index {idx} must include a 'template_fields' dict."
            )

    return sources


def _safe_substitute(template_str: str, fields: dict) -> str:
    """Perform safe template substitution (missing keys left as-is)."""
    tmpl = Template(template_str)
    return tmpl.safe_substitute(fields)


def render_section(
    source: dict,
    section_template: Optional[str] = None,
) -> str:
    """Render a single section from an internal source using template substitution.

    Args:
        source: Source dict with "name", "template_fields", and optionally
            "section_template" for a custom per-source template.
        section_template: Override template string. Uses source's own
            "section_template" field or the module default if None.

    Returns:
        Rendered section markdown string.
    """
    fields = dict(source.get("template_fields", {}))
    fields.setdefault("source_name", source.get("name", "Unknown"))
    fields.setdefault("last_updated", datetime.now().strftime("%Y-%m-%d"))
    fields.setdefault("section_title", source.get("name", "Section"))

    template = (
        section_template
        or source.get("section_template")
        or _DEFAULT_SECTION_TEMPLATE
    )

    return _safe_substitute(template, fields)


def run_internal_pipeline(
    sources_config: str,
    guide_path: Optional[str] = None,
    output_dir: str = "output",
    program_name: Optional[str] = None,
) -> bool:
    """Execute the internal data pipeline using template substitution only.

    Args:
        sources_config: Path to the internal sources JSON config.
        guide_path: Optional existing guide to append internal sections to.
            If None, generates a standalone internal supplement.
        output_dir: Directory where output files are written.
        program_name: Human-readable program name for the document header.

    Returns:
        True if output was generated successfully.
    """
    logger.info("step=1 action=load_internal_sources status=start path=%s", sources_config)
    sources = load_internal_sources(sources_config)
    logger.info("step=1 action=load_internal_sources status=done count=%d", len(sources))

    rendered_sections: list[str] = []
    for src in sources:
        name = src["name"]
        logger.info("step=2 action=render_section source=%s", name)
        section_md = render_section(src)
        rendered_sections.append(section_md)

    sections_combined = "\n---\n\n".join(rendered_sections)

    if program_name is None:
        program_name = Path(sources_config).stem.replace("_", " ").title()

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_md = _safe_substitute(_FULL_GUIDE_WRAPPER, {
        "program_name": program_name,
        "generated_at": generated_at,
        "sections": sections_combined,
    })

    if guide_path and os.path.exists(guide_path):
        with open(guide_path, "r", encoding="utf-8") as fh:
            existing_guide = fh.read()
        output_md = existing_guide.rstrip() + "\n\n---\n\n" + output_md

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "sponsor_guide_internal_supplement.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(output_md)
    logger.info("step=3 action=write_output status=done path=%s", out_path)

    return True


def main() -> None:
    """CLI entry point for the internal pipeline."""
    configure_rotating_file_logging(log_file=Path("logs") / "internal_pipeline.log")

    parser = argparse.ArgumentParser(
        description="Internal data pipeline — template substitution only, no LLM calls",
    )
    parser.add_argument(
        "--sources",
        required=True,
        help="Path to the internal sources JSON config",
    )
    parser.add_argument(
        "--guide",
        default=None,
        help="Optional existing guide to append internal sections to",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Output directory (default: output/)",
    )
    parser.add_argument(
        "--program-name",
        default=None,
        help="Human-readable program name for the document header",
    )
    args = parser.parse_args()

    success = run_internal_pipeline(
        sources_config=args.sources,
        guide_path=args.guide,
        output_dir=args.output,
        program_name=args.program_name,
    )
    if success:
        logger.info("result=success")
    else:
        logger.error("result=failed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
