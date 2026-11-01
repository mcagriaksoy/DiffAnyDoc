"""Tiny dependency-free XLSX writer used by tests.

Creates the minimum package parts the adapter reads: workbook, relationship
map, shared strings, a two-entry style table (general + date) and worksheets.
"""

from __future__ import annotations

import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

_S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

Cell = str | int | float | date | None


def _column(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _serial(value: date | datetime) -> float:
    if isinstance(value, datetime):
        delta = value - datetime(1899, 12, 30)
        return delta.days + (
            delta.seconds + delta.microseconds / 1_000_000
        ) / 86400
    return float((value - date(1899, 12, 30)).days)


def _worksheet(rows: list[list[Cell]], shared: list[str]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_S_NS}"><sheetData>'
    ]
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            if value is None:
                continue
            reference = f"{_column(column_index)}{row_index}"
            if isinstance(value, bool):
                cells.append(
                    f'<c r="{reference}" t="b"><v>{int(value)}</v></c>'
                )
            elif isinstance(value, (date, datetime)):
                cells.append(
                    f'<c r="{reference}" s="1"><v>{_serial(value):g}</v></c>'
                )
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                index = shared.index(value)
                cells.append(
                    f'<c r="{reference}" t="s"><v>{index}</v></c>'
                )
        parts.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def write_xlsx(
    path: Path,
    sheets: list[tuple[str, list[list[Cell]]]],
    *,
    title: str | None = None,
    date1904: bool = False,
) -> Path:
    shared: list[str] = []
    for _, rows in sheets:
        for row in rows:
            for value in row:
                if isinstance(value, str) and value not in shared:
                    shared.append(value)

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_S_NS}" xmlns:r="{_R_NS}">'
        f'<workbookPr date1904="{1 if date1904 else 0}"/>'
        "<sheets>"
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{index}" '
            f'r:id="rId{index}"/>'
            for index, (name, _) in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        + "</Relationships>"
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{_S_NS}" count="{len(shared)}" uniqueCount="{len(shared)}">'
        + "".join(f'<si><t xml:space="preserve">{escape(text)}</t></si>' for text in shared)
        + "</sst>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{_S_NS}"><cellXfs count="2">'
        '<xf numFmtId="0"/>'
        '<xf numFmtId="14" applyNumberFormat="1"/>'
        "</cellXfs></styleSheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        "</Types>"
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", package_rels)
        package.writestr("xl/workbook.xml", workbook)
        package.writestr("xl/_rels/workbook.xml.rels", relationships)
        package.writestr("xl/sharedStrings.xml", shared_xml)
        package.writestr("xl/styles.xml", styles)
        for index, (_, rows) in enumerate(sheets, start=1):
            package.writestr(
                f"xl/worksheets/sheet{index}.xml",
                _worksheet(rows, shared),
            )
        if title:
            core = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties'
                ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
                ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f"<dc:title>{escape(title)}</dc:title>"
                "</cp:coreProperties>"
            )
            package.writestr("docProps/core.xml", core)
    return path
