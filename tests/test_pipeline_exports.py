import zipfile
from pathlib import Path

import pipeline


def test_weekly_highlight_spans_convert_to_pdf_font_tags() -> None:
    html = pipeline._weekly_highlight_spans_to_pdf_html(
        '<span style="color: #c1121f;">Changed deadline</span>'
    )

    assert html == '<font color="#c1121f">Changed deadline</font>'


def test_docx_export_preserves_weekly_highlight_color(tmp_path: Path) -> None:
    docx_path = tmp_path / "guide.docx"

    pipeline._md_to_docx(
        "# Guide\n\n<span style=\"color: #c1121f;\">Changed deadline</span>",
        str(docx_path),
    )

    with zipfile.ZipFile(docx_path) as package:
        document_xml = package.read("word/document.xml").decode("utf-8")

    assert 'w:val="C1121F"' in document_xml
    assert "Changed deadline" in document_xml
