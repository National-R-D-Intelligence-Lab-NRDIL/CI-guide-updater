"""Pipeline orchestrator.

Ties together the scraper, differ, and updater modules into a single end-to-end
workflow:

    sources.json + guide.docx/md
            │
            ▼
    ┌───────────────┐
    │  1. Scrape     │  For each approved URL, fetch the latest page text
    │     (scraper)  │  and compare against the previous snapshot.
    └───────┬───────┘
            │ changed sources
            ▼
    ┌───────────────┐
    │  2. Diff       │  For every source that changed, produce a structured
    │     (differ)   │  summary of additions / removals.
    └───────┬───────┘
            │ combined diff
            ▼
    ┌───────────────┐
    │  3. Update     │  Ask an LLM to rewrite only the affected sections
    │     (updater)  │  of the Sponsor Guide.
    └───────┬───────┘
            │
            ▼
    output/sponsor_guide_updated.md  +  .docx
"""

import argparse
import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import mammoth
from dotenv import load_dotenv

import cite
import differ
import scraper
import updater
import weekly_update
from src.exporters.docx_export import md_to_docx as _md_to_docx
from src.exporters.pdf_export import md_to_pdf as _md_to_pdf
from src.utils.llm_client import get_default_model
from src.utils.logging_utils import configure_rotating_file_logging
from src.utils.sensitive_data import SensitiveDataError, enforce_sensitive_data_policy
from src.utils.source_policy import assert_public_sources

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_sources(config_path: str) -> list[dict]:
    """Load approved source URLs from a JSON config file.

    Expected format::

        [
          {"name": "NIH_R15", "url": "https://...", "data_class": "public"},
          ...
        ]

    Args:
        config_path: Path to the JSON file.

    Returns:
        List of validated source dicts with ``name``, ``sections``,
        ``data_class``, and either ``url`` or ``file_path``.
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        sources = json.load(fh)

    if not isinstance(sources, list):
        raise ValueError("sources.json must contain a JSON array")

    for idx, src in enumerate(sources):
        if not isinstance(src, dict):
            raise ValueError(f"Source at index {idx} must be an object")

        name = str(src.get("name", "")).strip()
        url = str(src.get("url", "")).strip()
        file_path = str(src.get("file_path", "")).strip()
        if not name or (not url and not file_path):
            raise ValueError(
                f"Source at index {idx} must include non-empty 'name' and either 'url' or 'file_path'"
            )

        sections = src.get("sections", [])
        if sections is None:
            sections = []
        if not isinstance(sections, list):
            raise ValueError(f"Source at index {idx} must use a list for 'sections'")

        data_class = str(src.get("data_class", "")).strip().lower()
        if data_class != "public":
            raise ValueError(
                f"Source '{name}' at index {idx} must set data_class to 'public' before it can be used."
            )

        src["name"] = name
        src["url"] = url
        src["file_path"] = file_path
        src["sections"] = sections
        src["data_class"] = "public"

    return sources


def read_guide(path: str) -> str:
    """Read a Sponsor Guide and return its content as markdown.

    Supports ``.docx`` (converted via *mammoth*) and ``.md`` / ``.txt``
    (read verbatim).

    Args:
        path: File path to the guide.

    Returns:
        Markdown string.

    Raises:
        ValueError: If the file extension is not supported.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        with open(path, "rb") as fh:
            result = mammoth.convert_to_markdown(fh)
            if result.messages:
                for msg in result.messages:
                    logger.warning("event=mammoth_message detail=%s", msg)
            return result.value
    if ext in (".md", ".txt"):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    raise ValueError(
        f"Unsupported guide format '{ext}'. Use .docx, .md, or .txt."
    )


def write_guide_md(path: str, content: str) -> None:
    """Write the updated markdown guide to *path*."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _artifact_timestamp() -> str:
    """Return a filename-safe local timestamp for run history artifacts."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _timestamped_output_path(output_dir: str, stem: str, suffix: str, timestamp: str) -> str:
    """Build a timestamped output artifact path."""
    return os.path.join(output_dir, f"{stem}_{timestamp}{suffix}")


# ---------------------------------------------------------------------------
# Snapshot reader
# ---------------------------------------------------------------------------

def _read_snapshot(name: str, data_dir: str) -> str:
    """Return the previously saved text snapshot, or ``""`` on first run."""
    path = os.path.join(data_dir, f"{name}_latest.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return ""


def _read_snapshot_metadata(name: str, data_dir: str) -> dict:
    """Return extraction metadata sidecar for a source snapshot, if present."""
    path = os.path.join(data_dir, f"{name}_latest.meta.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    return {}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    sources_config: str,
    guide_path: str,
    output_dir: str = "output",
    model_name: Optional[str] = None,
    state_file: Optional[str] = None,
    data_dir: Optional[str] = None,
    with_citations: bool = True,
    citation_model: Optional[str] = None,
    refresh_citations: bool = False,
    refresh_citations_only: bool = False,
) -> bool:
    """Execute the full scrape → diff → update pipeline.

    Args:
        sources_config: Path to the JSON file listing approved source URLs.
        guide_path: Path to the current Sponsor Guide (``.docx`` or ``.md``).
        output_dir: Directory where updated guide files are written.
        model_name: LLM model identifier forwarded to the updater.

    Returns:
        ``True`` if the guide was updated, ``False`` if no changes were found.
    """
    if model_name is None:
        model_name = get_default_model()

    # -- 1. Load inputs -------------------------------------------------------
    sources_root = os.path.dirname(os.path.abspath(sources_config)) or "."
    if state_file is None:
        state_file = os.path.join(sources_root, "state.json")
    if data_dir is None:
        data_dir = os.path.join(sources_root, "data")

    logger.info("step=1 action=load_inputs status=start")
    sources = load_sources(sources_config)
    guide_md_raw = read_guide(guide_path)
    guide_md = weekly_update.strip_weekly_update_markup(guide_md_raw)
    assert_public_sources(sources, context="pipeline")
    logger.info(
        "step=1 action=load_inputs status=done sources=%d guide_path=%s state_file=%s data_dir=%s",
        len(sources),
        guide_path,
        state_file,
        data_dir,
    )

    # -- 2. Scrape & diff -----------------------------------------------------
    all_diffs: list[tuple[str, list[str], str]] = []
    if refresh_citations_only:
        refresh_citations = True
        logger.info("step=2 action=scrape_diff status=skipped reason=refresh_citations_only")
    else:
        logger.info("step=2 action=scrape_diff status=start")
        for src in sources:
            name = src["name"]
            sections = src.get("sections", [])
            old_text = _read_snapshot(name, data_dir)

            try:
                changed = scraper.check_for_updates_from_source(
                    src,
                    name,
                    state_file=state_file,
                    data_dir=data_dir,
                )
            except Exception as exc:
                logger.warning("step=2 source=%s status=scrape_failed error=%s", name, exc)
                continue

            if changed:
                new_text = _read_snapshot(name, data_dir)
                diff = differ.extract_changes(old_text, new_text)

                if not sections:
                    try:
                        sections = updater.classify_sections(new_text, guide_md)
                        if sections:
                            logger.info(
                                "step=2 source=%s status=sections_autodetected sections=%s",
                                name,
                                ",".join(sections),
                            )
                    except Exception:
                        pass

                all_diffs.append((name, sections, diff))
                logger.info("step=2 source=%s status=changed", name)
            else:
                logger.info("step=2 source=%s status=unchanged", name)

    if not all_diffs and not refresh_citations:
        logger.info("result=up_to_date reason=no_source_changes")
        return False

    updated_md = guide_md
    did_llm_update = False
    combined_diff = ""
    changed_source_names: list[str] = []
    if all_diffs:
        # -- 3. Update via LLM ------------------------------------------------
        logger.info("step=3 action=llm_update status=start diffs=%d model=%s", len(all_diffs), model_name)

        diff_blocks: list[str] = []
        for name, sections, diff in all_diffs:
            changed_source_names.append(name)
            header = f"## Source: {name}"
            if sections:
                header += (
                    "\nRelevant guide sections: "
                    + ", ".join(f'"{s}"' for s in sections)
                )
            enforce_sensitive_data_policy(
                diff,
                context=f"pipeline update source '{name}'",
                allow_public_contextual_findings=True,
            )
            diff_blocks.append(f"{header}\n\n{diff}")
        combined_diff = "\n\n".join(diff_blocks)

        try:
            assert_public_sources(sources, context="pipeline update step")
            updated_md = updater.update_guide(
                guide_md,
                combined_diff,
                model_name,
                allow_public_contextual_findings=True,
            )
            did_llm_update = True
        except EnvironmentError as exc:
            logger.error("step=3 action=llm_update status=error type=config error=%s", exc)
            return False
        except Exception as exc:
            logger.error("step=3 action=llm_update status=error type=llm_call error=%s", exc)
            return False
    else:
        logger.info("step=3 action=llm_update status=skipped reason=no_diffs")

    if did_llm_update:
        updated_md = weekly_update.decorate_weekly_update(
            previous_md=guide_md,
            updated_md=updated_md,
            changed_sources=changed_source_names,
            source_diffs=[(name, diff) for name, _sections, diff in all_diffs],
        )
        logger.info("step=3 action=weekly_update_markup status=done")

    # -- 4. Optional citation pass --------------------------------------------
    evidence: list[dict] = []
    if with_citations:
        assert_public_sources(sources, context="pipeline citation step")
        logger.info("step=4 action=citation_pass status=start")
        snapshot_map: dict[str, str] = {}
        source_metadata_map: dict[str, dict] = {}
        for src in sources:
            name = src["name"]
            txt = _read_snapshot(name, data_dir)
            source_metadata_map[name] = _read_snapshot_metadata(name, data_dir)
            if not txt and not refresh_citations_only:
                try:
                    payload = scraper.fetch_source_payload_from_source(src)
                    txt = payload.get("text", "")
                    meta = payload.get("metadata", {})
                    if isinstance(meta, dict):
                        source_metadata_map[name] = meta
                except Exception:
                    txt = ""
            snapshot_map[name] = txt
        try:
            cited_md, evidence = cite.add_citations(
                updated_md,
                sources=sources,
                snapshots_by_name=snapshot_map,
                source_metadata_by_name=source_metadata_map,
                model_name=citation_model or model_name,
            )
            if evidence:
                updated_md = cited_md
                logger.info("step=4 action=citation_pass status=done claims=%d", len(evidence))
            else:
                logger.warning("step=4 action=citation_pass status=no_validated_citations")
        except Exception as exc:
            if isinstance(exc, SensitiveDataError):
                logger.error("step=4 action=citation_pass status=blocked error=%s", exc)
                return False
            logger.warning(
                "step=4 action=citation_pass status=failed error=%s fallback=continue_without_citations",
                exc,
            )

    # -- 5. Write outputs ------------------------------------------------------
    step_label = "[5/5]" if with_citations else "[4/4]"
    logger.info("step=%s action=save_outputs status=start", step_label.strip("[]"))
    os.makedirs(output_dir, exist_ok=True)
    run_stamp = _artifact_timestamp()

    md_path = os.path.join(output_dir, "sponsor_guide_updated.md")
    timestamped_md_path = _timestamped_output_path(
        output_dir,
        "sponsor_guide_updated",
        ".md",
        run_stamp,
    )
    write_guide_md(md_path, updated_md)
    logger.info("step=5 artifact=markdown status=saved path=%s", md_path)
    write_guide_md(timestamped_md_path, updated_md)
    logger.info("step=5 artifact=markdown_timestamped status=saved path=%s", timestamped_md_path)

    docx_path = os.path.join(output_dir, "sponsor_guide_updated.docx")
    timestamped_docx_path = _timestamped_output_path(
        output_dir,
        "sponsor_guide_updated",
        ".docx",
        run_stamp,
    )
    try:
        _md_to_docx(updated_md, docx_path)
        logger.info("step=5 artifact=docx status=saved path=%s", docx_path)
        shutil.copyfile(docx_path, timestamped_docx_path)
        logger.info("step=5 artifact=docx_timestamped status=saved path=%s", timestamped_docx_path)
    except Exception as exc:
        logger.warning("step=5 artifact=docx status=failed error=%s", exc)

    pdf_path = os.path.join(output_dir, "sponsor_guide_updated.pdf")
    timestamped_pdf_path = _timestamped_output_path(
        output_dir,
        "sponsor_guide_updated",
        ".pdf",
        run_stamp,
    )
    try:
        _md_to_pdf(updated_md, pdf_path)
        logger.info("step=5 artifact=pdf status=saved path=%s", pdf_path)
        shutil.copyfile(pdf_path, timestamped_pdf_path)
        logger.info("step=5 artifact=pdf_timestamped status=saved path=%s", timestamped_pdf_path)
    except ImportError as exc:
        logger.warning("step=5 artifact=pdf status=skipped reason=dependency_missing error=%s", exc)
    except Exception as exc:
        logger.warning("step=5 artifact=pdf status=failed error=%s", exc)

    if with_citations and evidence:
        evidence_path = os.path.join(output_dir, "sponsor_guide_evidence.json")
        timestamped_evidence_path = _timestamped_output_path(
            output_dir,
            "sponsor_guide_evidence",
            ".json",
            run_stamp,
        )
        with open(evidence_path, "w", encoding="utf-8") as fh:
            json.dump(evidence, fh, indent=2)
        logger.info("step=5 artifact=evidence status=saved path=%s", evidence_path)
        with open(timestamped_evidence_path, "w", encoding="utf-8") as fh:
            json.dump(evidence, fh, indent=2)
        logger.info("step=5 artifact=evidence_timestamped status=saved path=%s", timestamped_evidence_path)

    if did_llm_update:
        logger.info("result=updated changed_sources=%s", ",".join(n for n, _, _ in all_diffs))
    else:
        logger.info("result=citations_refreshed")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point when invoked from the command line."""
    configure_rotating_file_logging(log_file=Path("logs") / "pipeline.log")
    load_dotenv(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(
        description="Sponsor Guide update pipeline — scrape → diff → LLM update",
    )
    parser.add_argument(
        "guide",
        help="Path to the current Sponsor Guide (.docx or .md)",
    )
    parser.add_argument(
        "--sources",
        default="sources.json",
        help="Path to the approved-sources JSON config (default: sources.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: <sources_dir>/output/)",
    )
    parser.add_argument(
        "--state",
        default=None,
        help="Path to state.json (default: <sources_dir>/state.json)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory for text snapshots (default: <sources_dir>/data/)",
    )
    parser.add_argument(
        "--model",
        default=get_default_model(),
        help=f"LLM model name (default: {get_default_model()})",
    )
    parser.add_argument(
        "--with-citations",
        dest="with_citations",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-citations",
        dest="with_citations",
        action="store_false",
        help="Disable citation pass (enabled by default).",
    )
    parser.add_argument(
        "--citation-model",
        default=None,
        help="Model used for citation mapping (default: same as --model).",
    )
    parser.add_argument(
        "--refresh-citations",
        action="store_true",
        help=(
            "Run citation pass even when no source diffs are detected "
            "(guide text is left unchanged)."
        ),
    )
    parser.add_argument(
        "--refresh-citations-only",
        action="store_true",
        help=(
            "Skip scrape/diff and only regenerate citations/evidence for the current guide "
            "using existing snapshots in the program data folder."
        ),
    )
    parser.set_defaults(with_citations=True)
    args = parser.parse_args()

    output_dir = args.output
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(args.sources)), "output")

    run_pipeline(
        args.sources,
        args.guide,
        output_dir,
        args.model,
        state_file=args.state,
        data_dir=args.data_dir,
        with_citations=args.with_citations,
        citation_model=args.citation_model,
        refresh_citations=args.refresh_citations,
        refresh_citations_only=args.refresh_citations_only,
    )


if __name__ == "__main__":
    main()
