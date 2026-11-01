"""Tiny dependency-free DOCX writer used by tests.

Real Word files are ZIP packages around ``word/document.xml``. The adapter only
reads the body and core properties, so the fixtures create exactly that, with
the minimum package parts needed for the file to look like a DOCX.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

Block = tuple[str, object]


def _paragraph(text: str, style: str | None = None) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{escape(style)}"/></w:pPr>' if style else ""
    return (
        "<w:p>"
        + properties
        + '<w:r><w:t xml:space="preserve">'
        + escape(text)
        + "</w:t></w:r></w:p>"
    )


def _page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def _table(rows: list[list[str]], header: bool = True) -> str:
    out = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/></w:tblPr>']
    for index, row in enumerate(rows):
        properties = (
            "<w:trPr><w:tblHeader/></w:trPr>"
            if header and index == 0
            else ""
        )
        cells = "".join(
            "<w:tc>" + _paragraph(cell) + "</w:tc>" for cell in row
        )
        out.append(f"<w:tr>{properties}{cells}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def _body(blocks: list[Block]) -> str:
    parts: list[str] = []
    for block in blocks:
        kind = block[0]
        if kind == "p":
            parts.append(_paragraph(str(block[1]), block[2] if len(block) > 2 else None))  # type: ignore[arg-type]
        elif kind == "pagebreak":
            parts.append(_page_break())
        elif kind == "table":
            parts.append(_table(block[1]))  # type: ignore[arg-type]
        else:  # pragma: no cover - test helper misuse
            raise ValueError(f"unknown block {kind!r}")
    return "".join(parts)


def write_docx(
    path: Path,
    blocks: list[Block],
    *,
    title: str | None = None,
    creator: str | None = None,
) -> Path:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}"><w:body>'
        + _body(blocks)
        + "<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", relationships)
        package.writestr("word/document.xml", document)
        if title or creator:
            core = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties'
                ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
                ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
                + (f"<dc:title>{escape(title)}</dc:title>" if title else "")
                + (f"<dc:creator>{escape(creator)}</dc:creator>" if creator else "")
                + "</cp:coreProperties>"
            )
            package.writestr("docProps/core.xml", core)
    return path
