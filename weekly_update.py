"""Weekly update presentation helpers.

This module decorates a clean updated Sponsor Guide with:
- a short update banner at the top of the document
- red highlights around lines that changed during the weekly update

The helpers are deterministic and do not call the LLM. They are applied only
after a baseline guide already exists and a weekly update detects source diffs.
"""

from __future__ import annotations

import difflib
import re
from datetime import date


HIGHLIGHT_COLOR = "#c1121f"


def _strip_existing_update_banner(markdown: str) -> str:
    """Remove a prior generated weekly update banner, if present."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "<!-- weekly-update-banner:start -->":
        return markdown

    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "<!-- weekly-update-banner:end -->":
            remaining = lines[idx + 1 :]
            while remaining and not remaining[0].strip():
                remaining.pop(0)
            return "\n".join(remaining)
    return markdown


def _strip_highlight_spans(markdown: str) -> str:
    """Remove generated red span wrappers from a previous weekly output."""
    span_re = re.compile(
        r'<span style="color:\s*#?c1121f;">(.*?)</span>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    return span_re.sub(r"\1", markdown)


def strip_weekly_update_markup(markdown: str) -> str:
    """Return markdown without generated weekly-update banner/highlight markup."""
    return _strip_highlight_spans(_strip_existing_update_banner(markdown))


def _highlight_line(line: str) -> str:
    """Wrap visible markdown line content in a red span while preserving syntax."""
    if not line.strip():
        return line
    if line.lstrip().startswith("<!--"):
        return line
    if line.strip().startswith("<span ") and line.strip().endswith("</span>"):
        return line

    heading = re.match(r"^(\s{0,3}#{1,6}\s+)(.+)$", line)
    if heading:
        return f'{heading.group(1)}<span style="color: {HIGHLIGHT_COLOR};">{heading.group(2)}</span>'

    bullet = re.match(r"^(\s*(?:[-*+]|\d+\.)\s+)(.+)$", line)
    if bullet:
        return f'{bullet.group(1)}<span style="color: {HIGHLIGHT_COLOR};">{bullet.group(2)}</span>'

    quote = re.match(r"^(\s*>\s?)(.+)$", line)
    if quote:
        return f'{quote.group(1)}<span style="color: {HIGHLIGHT_COLOR};">{quote.group(2)}</span>'

    if line.startswith("|") and line.endswith("|"):
        cells = line.split("|")
        highlighted = []
        for idx, cell in enumerate(cells):
            if idx in {0, len(cells) - 1}:
                highlighted.append(cell)
            elif cell.strip() and not re.fullmatch(r"\s*:?-{3,}:?\s*", cell):
                leading = cell[: len(cell) - len(cell.lstrip())]
                trailing = cell[len(cell.rstrip()) :]
                core = cell.strip()
                highlighted.append(
                    f'{leading}<span style="color: {HIGHLIGHT_COLOR};">{core}</span>{trailing}'
                )
            else:
                highlighted.append(cell)
        return "|".join(highlighted)

    return f'<span style="color: {HIGHLIGHT_COLOR};">{line}</span>'


def highlight_changed_main_text(previous_md: str, updated_md: str) -> str:
    """Highlight inserted/replaced lines in ``updated_md`` compared with ``previous_md``.

    Deletions cannot be highlighted in the main text because they no longer
    exist in the updated document; the banner summarizes those instead.
    """
    previous_clean = strip_weekly_update_markup(previous_md)
    updated_clean = strip_weekly_update_markup(updated_md)

    old_lines = previous_clean.splitlines()
    new_lines = updated_clean.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    changed_new_indexes: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "insert"}:
            changed_new_indexes.update(range(j1, j2))

    decorated = [
        _highlight_line(line) if idx in changed_new_indexes else line
        for idx, line in enumerate(new_lines)
    ]
    return "\n".join(decorated)


def _plain_summary_text(line: str) -> str:
    """Return a compact human-readable summary for one markdown line."""
    text = strip_weekly_update_markup(line)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", text)
    text = text.strip().strip("|").strip()
    if re.fullmatch(r":?-{3,}:?", text.replace("|", "").strip()):
        return ""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def summarize_guide_changes(previous_md: str, updated_md: str, limit: int = 6) -> list[str]:
    """Return concise bullets from actual guide text changes, not source-page noise."""
    previous_clean = strip_weekly_update_markup(previous_md)
    updated_clean = strip_weekly_update_markup(updated_md)
    old_lines = previous_clean.splitlines()
    new_lines = updated_clean.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    items: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "insert"}:
            items.extend(
                _plain_summary_text(line)
                for line in new_lines[j1:j2]
            )
        elif tag == "delete":
            items.extend(
                f"Removed: {_plain_summary_text(line)}"
                for line in old_lines[i1:i2]
            )

    compact: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        if len(normalized) > 180:
            normalized = normalized[:177].rstrip() + "..."
        compact.append(normalized)
        if len(compact) >= limit:
            break
    return compact


def _source_label(source_name: str) -> str:
    """Make source identifiers more readable in the banner."""
    label = str(source_name or "").strip()
    label = re.sub(r"^[a-z0-9]+(?:_[a-z0-9]+){0,8}_", "", label)
    label = label.replace("_", " ")
    label = re.sub(r"\s+", " ", label).strip()
    return label.title() if label else "Approved Source"


def build_update_banner(
    guide_change_bullets: list[str],
    changed_sources: list[str],
    *,
    run_date: date | None = None,
) -> str:
    """Build a top-of-document banner summarizing weekly update changes."""
    run_date = run_date or date.today()
    bullets = [item for item in guide_change_bullets if item.strip()]

    source_labels = [_source_label(source) for source in changed_sources[:5]]
    source_text = ", ".join(source_labels) if source_labels else "approved sources"
    if len(changed_sources) > 5:
        source_text += f", and {len(changed_sources) - 5} more"

    lines = [
        "<!-- weekly-update-banner:start -->",
        "## Weekly Update",
        "",
        f"**Updated:** {run_date.isoformat()}  ",
        f"**Changed sources:** {source_text}",
        "",
        "> Important changes from this run:",
        "",
    ]
    lines.extend(f"- {item}" for item in bullets)
    lines.extend(
        [
            "",
            f'<span style="color: {HIGHLIGHT_COLOR};">Red text marks guide content changed by this weekly update.</span>',
            "<!-- weekly-update-banner:end -->",
        ]
    )
    return "\n".join(lines)


def decorate_weekly_update(
    previous_md: str,
    updated_md: str,
    changed_sources: list[str],
) -> str:
    """Add the weekly update banner and red changed-text highlights."""
    guide_change_bullets = summarize_guide_changes(previous_md, updated_md)
    if not guide_change_bullets:
        return strip_weekly_update_markup(updated_md)

    highlighted = highlight_changed_main_text(previous_md, updated_md)
    banner = build_update_banner(guide_change_bullets, changed_sources)
    return f"{banner}\n\n{highlighted}"
