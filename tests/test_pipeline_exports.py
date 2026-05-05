import zipfile
from pathlib import Path

from src.exporters.docx_export import md_to_docx
from src.exporters.pdf_export import md_to_pdf, _weekly_highlight_spans_to_pdf_html


def test_weekly_highlight_spans_convert_to_pdf_font_tags() -> None:
    html = _weekly_highlight_spans_to_pdf_html(
        '<span style="color: #c1121f;">Changed deadline</span>'
    )

    assert html == '<font color="#c1121f">Changed deadline</font>'


def test_docx_export_preserves_weekly_highlight_color(tmp_path: Path) -> None:
    docx_path = tmp_path / "guide.docx"

    md_to_docx(
        "# Guide\n\n<span style=\"color: #c1121f;\">Changed deadline</span>",
        str(docx_path),
    )

    with zipfile.ZipFile(docx_path) as package:
        document_xml = package.read("word/document.xml").decode("utf-8")

    assert 'w:val="C1121F"' in document_xml
    assert "Changed deadline" in document_xml


def test_docx_export_strips_comment_markers_and_span_tags_from_headings(tmp_path: Path) -> None:
    docx_path = tmp_path / "guide.docx"

    md_to_docx(
        "<!-- weekly-update-banner:end -->\n"
        '## <span style="color: #c1121f;">Cost Share Requirements</span>',
        str(docx_path),
    )

    with zipfile.ZipFile(docx_path) as package:
        document_xml = package.read("word/document.xml").decode("utf-8")

    assert "weekly-update-banner" not in document_xml
    assert "&lt;span" not in document_xml
    assert "Cost Share Requirements" in document_xml
    assert 'w:val="C1121F"' in document_xml


def test_pdf_export_uses_explicit_red_color_for_weekly_highlights(tmp_path: Path) -> None:
    pdf_path = tmp_path / "guide.pdf"

    md_to_pdf(
        '<span style="color: #c1121f;">Changed deadline</span>',
        str(pdf_path),
    )

    raw_pdf = pdf_path.read_bytes()
    assert b"Changed deadline" in raw_pdf
    assert b"0.7569 0.0706 0.1216 rg" in raw_pdf
