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
import os
import re
from pathlib import Path

import mammoth
from docx import Document
from docx.shared import Pt
from dotenv import load_dotenv

import differ
import scraper
import updater

DATA_DIR = scraper.DATA_DIR


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_sources(config_path: str) -> list[dict]:
    """Load approved source URLs from a JSON config file.

    Expected format::

        [
          {"name": "NIH_R15", "url": "https://..."},
          ...
        ]

    Args:
        config_path: Path to the JSON file.

    Returns:
        List of source dicts, each containing ``name`` and ``url``.
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


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
                    print(f"       [mammoth] {msg}")
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


# ---------------------------------------------------------------------------
# Markdown → .docx converter (basic)
# ---------------------------------------------------------------------------

def _md_to_docx(md_text: str, path: str) -> None:
    """Convert markdown text to a ``.docx`` file.

    Handles headings, paragraphs, bold / italic, bullet lists, and simple
    pipe-delimited tables — enough for a typical Sponsor Guide.
    """
    doc = Document()
    doc.styles["Normal"].font.size = Pt(11)

    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # --- headings ---
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            doc.add_heading(m.group(2).strip(), level=len(m.group(1)))
            i += 1
            continue

        # --- table ---
        if "|" in line and i + 1 < len(lines) and re.match(r"^[\s|:-]+$", lines[i + 1]):
            headers = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            table = doc.add_table(rows=1 + len(rows), cols=len(headers))
            table.style = "Table Grid"
            for ci, h in enumerate(headers):
                table.rows[0].cells[ci].text = h
            for ri, row in enumerate(rows):
                for ci, cell in enumerate(row):
                    if ci < len(headers):
                        table.rows[ri + 1].cells[ci].text = cell
            continue

        # --- bullet list ---
        m = re.match(r"^[-*]\s+(.+)$", line)
        if m:
            doc.add_paragraph(m.group(1), style="List Bullet")
            i += 1
            continue

        # --- blank line ---
        if not line.strip():
            i += 1
            continue

        # --- regular paragraph ---
        p = doc.add_paragraph()
        _add_inline_formatting(p, line)
        i += 1

    doc.save(path)


def _add_inline_formatting(paragraph, text: str) -> None:
    """Parse **bold** and *italic* markup and add styled runs."""
    pattern = re.compile(r"(\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*)")
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos : m.start()])
        if m.group(2):
            run = paragraph.add_run(m.group(2))
            run.bold = True
            run.italic = True
        elif m.group(3):
            run = paragraph.add_run(m.group(3))
            run.bold = True
        elif m.group(4):
            run = paragraph.add_run(m.group(4))
            run.italic = True
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


# ---------------------------------------------------------------------------
# Snapshot reader
# ---------------------------------------------------------------------------

def _read_snapshot(name: str) -> str:
    """Return the previously saved text snapshot, or ``""`` on first run."""
    path = os.path.join(DATA_DIR, f"{name}_latest.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return ""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    sources_config: str,
    guide_path: str,
    output_dir: str = "output",
    model_name: str = updater.DEFAULT_MODEL,
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
    # -- 1. Load inputs -------------------------------------------------------
    print("[1/4] Loading sources and guide ...")
    sources = load_sources(sources_config)
    guide_md = read_guide(guide_path)
    print(f"       {len(sources)} source(s)  •  guide loaded from {guide_path}")

    # -- 2. Scrape & diff -----------------------------------------------------
    print("[2/4] Checking sources for updates ...")
    all_diffs: list[tuple[str, list[str], str]] = []

    for src in sources:
        name, url = src["name"], src["url"]
        sections = src.get("sections", [])
        old_text = _read_snapshot(name)

        try:
            changed = scraper.check_for_updates(url, name)
        except Exception as exc:
            print(f"       ⚠  {name}: scrape failed — {exc}")
            continue

        if changed:
            new_text = _read_snapshot(name)
            diff = differ.extract_changes(old_text, new_text)
            all_diffs.append((name, sections, diff))
            print(f"       ✓  {name}: changes detected")
        else:
            print(f"       ·  {name}: no changes")

    if not all_diffs:
        print("\n[result] All sources unchanged — guide is up to date.")
        return False

    # -- 3. Update via LLM ----------------------------------------------------
    print(f"[3/4] Sending {len(all_diffs)} diff(s) to LLM ({model_name}) ...")

    diff_blocks: list[str] = []
    for name, sections, diff in all_diffs:
        header = f"## Source: {name}"
        if sections:
            header += (
                "\nRelevant guide sections: "
                + ", ".join(f'"{s}"' for s in sections)
            )
        diff_blocks.append(f"{header}\n\n{diff}")
    combined_diff = "\n\n".join(diff_blocks)

    try:
        updated_md = updater.update_guide(guide_md, combined_diff, model_name)
    except EnvironmentError as exc:
        print(f"\n[error] {exc}")
        return False
    except Exception as exc:
        print(f"\n[error] LLM call failed — {exc}")
        return False

    # -- 4. Write outputs ------------------------------------------------------
    print("[4/4] Saving updated guide ...")
    os.makedirs(output_dir, exist_ok=True)

    md_path = os.path.join(output_dir, "sponsor_guide_updated.md")
    write_guide_md(md_path, updated_md)
    print(f"       ✓  Markdown → {md_path}")

    docx_path = os.path.join(output_dir, "sponsor_guide_updated.docx")
    try:
        _md_to_docx(updated_md, docx_path)
        print(f"       ✓  Word     → {docx_path}")
    except Exception as exc:
        print(f"       ⚠  .docx export failed ({exc}); markdown saved OK")

    print(f"\n[result] Guide updated with changes from: "
          f"{', '.join(n for n, _, _ in all_diffs)}")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point when invoked from the command line."""
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
        default="output",
        help="Output directory for the updated guide (default: output/)",
    )
    parser.add_argument(
        "--model",
        default=updater.DEFAULT_MODEL,
        help=f"LLM model name (default: {updater.DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    run_pipeline(args.sources, args.guide, args.output, args.model)


if __name__ == "__main__":
    main()
