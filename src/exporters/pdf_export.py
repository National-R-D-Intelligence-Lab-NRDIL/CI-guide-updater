"""Markdown to PDF converter using fpdf2 (pure Python, zero system dependencies).

Supports weekly-update red highlight spans, headings, bullets, blockquotes,
and pipe-delimited tables via the Python markdown library's HTML output.
"""

import re
import unicodedata
from typing import Optional

try:
    import markdown as _markdown_lib
    from fpdf import FPDF as _FPDF
    _PDF_AVAILABLE = True
except Exception:
    _PDF_AVAILABLE = False

_WEEKLY_HIGHLIGHT_SPAN_RE = re.compile(
    r"<span\s+style=[\"']color:\s*#?c1121f;?[\"']>(.*?)</span>",
    flags=re.IGNORECASE | re.DOTALL,
)

_UNICODE_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": ",",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2013": "-",
    "\u2014": "--",
    "\u2015": "--",
    "\u2026": "...",
    "\u00a0": " ",
    "\u00b7": "*",
    "\u2022": "*",
    "\u2023": "*",
    "\u2032": "'",
    "\u2033": '"',
}

_LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s")


def _is_html_comment_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("<!--") and stripped.endswith("-->")


def _strip_markdown_links(text: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def _weekly_highlight_spans_to_pdf_html(text: str) -> str:
    return _WEEKLY_HIGHLIGHT_SPAN_RE.sub(
        r'<font color="#c1121f">\1</font>',
        text,
    )


def _plain_text_segments_from_weekly_spans(text: str) -> list[tuple[str, bool]]:
    """Split text into plain segments and weekly-highlight flags."""
    segments: list[tuple[str, bool]] = []
    pos = 0
    for match in _WEEKLY_HIGHLIGHT_SPAN_RE.finditer(text):
        if match.start() > pos:
            segments.append((_strip_markdown_links(text[pos : match.start()]), False))
        segments.append((_strip_markdown_links(match.group(1)), True))
        pos = match.end()
    if pos < len(text):
        segments.append((_strip_markdown_links(text[pos:]), False))
    return [(segment, highlighted) for segment, highlighted in segments if segment]


def _sanitize_for_pdf(text: str) -> str:
    """Replace Unicode characters unsupported by fpdf2's Latin-1 core fonts."""
    for char, replacement in _UNICODE_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    result = []
    for char in text:
        if ord(char) <= 255:
            result.append(char)
        else:
            normalized = unicodedata.normalize("NFKD", char)
            ascii_equiv = normalized.encode("ascii", "ignore").decode("ascii")
            result.append(ascii_equiv if ascii_equiv else "?")
    return "".join(result)


def _ensure_blank_before_lists(md_text: str) -> str:
    """Insert a blank line before list items that immediately follow non-list text."""
    lines = md_text.split("\n")
    result: list[str] = []
    for i, line in enumerate(lines):
        if _LIST_ITEM_RE.match(line) and i > 0:
            prev = result[-1] if result else ""
            if prev.strip() and not _LIST_ITEM_RE.match(prev):
                result.append("")
        result.append(line)
    return "\n".join(result)


def _write_pdf_segments(pdf, text: str, *, font_size: int = 11, bold: bool = False) -> None:
    """Write one logical line to PDF, switching to red for highlighted spans."""
    pdf.set_font("Helvetica", "B" if bold else "", font_size)
    segments = _plain_text_segments_from_weekly_spans(text)
    if not segments:
        pdf.ln(font_size + 3)
        return
    for segment, highlighted in segments:
        if highlighted:
            pdf.set_text_color(193, 18, 31)
        else:
            pdf.set_text_color(0, 0, 0)
        cleaned = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", segment)
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
        pdf.write(font_size + 3, cleaned)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(font_size + 5)


def _md_to_pdf_with_highlights(md_text: str, path: str) -> None:
    """Render markdown with explicit red weekly-update highlights."""
    pdf = _FPDF(orientation="P", unit="pt", format="Letter")
    pdf.set_compression(False)
    pdf.set_margins(left=72, top=72, right=72)
    pdf.set_auto_page_break(auto=True, margin=72)
    pdf.add_page()

    for line in _sanitize_for_pdf(md_text).splitlines():
        if _is_html_comment_line(line):
            continue
        if not line.strip():
            pdf.ln(6)
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            font_size = max(12, 20 - (level * 2))
            _write_pdf_segments(pdf, heading.group(2).strip(), font_size=font_size, bold=True)
            continue

        bullet = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.+)$", line)
        if bullet:
            marker = bullet.group(2)
            content = bullet.group(3)
            prefix = f"{marker} " if marker.endswith(".") else "* "
            _write_pdf_segments(pdf, prefix + content, font_size=11)
            continue

        quote_m = re.match(r"^>\s?(.+)$", line)
        if quote_m:
            _write_pdf_segments(pdf, "  " + quote_m.group(1), font_size=10)
            continue

        _write_pdf_segments(pdf, line, font_size=11)

    pdf.output(path)


def md_to_pdf(md_text: str, path: str) -> None:
    """Convert markdown to a styled PDF.

    Raises:
        ImportError: If markdown or fpdf2 are not installed.
    """
    if not _PDF_AVAILABLE:
        raise ImportError(
            "PDF export requires 'markdown' and 'fpdf2'. "
            "Run: pip3 install markdown fpdf2"
        )

    if _WEEKLY_HIGHLIGHT_SPAN_RE.search(md_text):
        _md_to_pdf_with_highlights(md_text, path)
        return

    safe_md = _sanitize_for_pdf(md_text)
    safe_md = _weekly_highlight_spans_to_pdf_html(safe_md)
    safe_md = _ensure_blank_before_lists(safe_md)

    body_html = _markdown_lib.markdown(
        safe_md,
        extensions=["tables", "fenced_code", "sane_lists"],
    )

    body_html = body_html.replace("<table>", '<table width="100%">')
    body_html = body_html.replace("<th>", '<th align="left">')
    body_html = body_html.replace("<td>", '<td align="left">')

    full_html = f"<html><body>{body_html}</body></html>"

    pdf = _FPDF(orientation="P", unit="pt", format="Letter")
    pdf.set_margins(left=72, top=72, right=72)
    pdf.set_auto_page_break(auto=True, margin=72)
    pdf.add_page()
    pdf.write_html(full_html)
    pdf.output(path)
