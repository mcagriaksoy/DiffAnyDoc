"""Minimal OOXML writers for tests: no binary fixtures, no python-docx.

Writing the XML by hand also lets tests exercise exactly the constructs the
adapter must handle (tracked changes, numbering, footnotes, text boxes).
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
)

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:styles {NS}>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:numbering {NS}>
<w:abstractNum w:abstractNumId="0">
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
  <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2."/></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""


def run(text: str, *, bold: bool = False) -> str:
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def para(*runs: str, style: str | None = None, num: tuple[int, int] | None = None) -> str:
    ppr = ""
    if style or num:
        inner = f'<w:pStyle w:val="{style}"/>' if style else ""
        if num:
            inner += f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>'
        ppr = f"<w:pPr>{inner}</w:pPr>"
    body = "".join(r if r.startswith("<") else run(r) for r in runs)
    return f"<w:p>{ppr}{body}</w:p>"


def ins(text: str) -> str:
    return f'<w:ins w:id="90" w:author="Ada" w:date="2024-01-01T00:00:00Z">{run(text)}</w:ins>'


def delete(text: str) -> str:
    return (
        f'<w:del w:id="91" w:author="Ada" w:date="2024-01-01T00:00:00Z">'
        f'<w:r><w:delText xml:space="preserve">{escape(text)}</w:delText></w:r></w:del>'
    )


def footnote_ref(note_id: int) -> str:
    return f'<w:r><w:footnoteReference w:id="{note_id}"/></w:r>'


def table(rows: list[list[str]]) -> str:
    out = ["<w:tbl>"]
    for cells in rows:
        out.append("<w:tr>")
        for cell in cells:
            out.append(f"<w:tc>{para(cell)}</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def write_docx(
    path: Path,
    body: list[str],
    *,
    header: str | None = None,
    footnotes: dict[int, str] | None = None,
) -> Path:
    rels = [
        '<Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
        '<Relationship Id="rIdN" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>',
    ]
    files = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/styles.xml": STYLES,
        "word/numbering.xml": NUMBERING,
        "word/document.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}><w:body>'
            + "".join(body)
            + "<w:sectPr/></w:body></w:document>"
        ),
    }
    if header is not None:
        rels.append(
            '<Relationship Id="rIdH" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
        )
        files["word/header1.xml"] = f'<?xml version="1.0" encoding="UTF-8"?><w:hdr {NS}>{para(header)}</w:hdr>'
    if footnotes:
        rels.append(
            '<Relationship Id="rIdF" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
        )
        notes = '<w:footnote w:type="separator" w:id="-1"><w:p/></w:footnote>' + "".join(
            f'<w:footnote w:id="{key}">{para(text)}</w:footnote>' for key, text in footnotes.items()
        )
        files["word/footnotes.xml"] = f'<?xml version="1.0" encoding="UTF-8"?><w:footnotes {NS}>{notes}</w:footnotes>'
    files["word/_rels/document.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def write_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    return path
