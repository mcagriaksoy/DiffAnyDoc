"""XLSX adapter: sheets, rows and cells straight from the OOXML package.

Workbooks are read without a third-party library. Each sheet becomes a page
with one table block, so the diff engine can align rows and cells instead of
comparing a single blob of text. Cached formula results are used, which is
what a reader sees in Excel.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..model import Block, Document, Page
from .base import AdapterError
from .ooxml import core_properties, read_optional

_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_REF = re.compile(r"^([A-Za-z]+)(\d+)$")

#: Built-in number formats that Excel renders as dates or times.
_DATE_FORMAT_IDS = (
    set(range(14, 23))
    | set(range(27, 37))
    | set(range(45, 48))
    | set(range(50, 59))
)

#: Quoted literals and bracket sections in a format code, e.g. ``[Red]``.
_FORMAT_LITERAL = re.compile(r'"[^"]*"|\[[^\]]*\]')


class XlsxAdapter:
    name = "xlsx"
    extensions = (".xlsx", ".xlsm")

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def load(self, path: Path) -> Document:
        try:
            with zipfile.ZipFile(path) as package:
                try:
                    workbook_xml = package.read("xl/workbook.xml")
                except KeyError as exc:
                    raise AdapterError(
                        f"{path.name!r} is not a spreadsheet (no xl/workbook.xml)"
                    ) from exc
                rels_xml = read_optional(package, "xl/_rels/workbook.xml.rels")
                shared_xml = read_optional(package, "xl/sharedStrings.xml")
                styles_xml = read_optional(package, "xl/styles.xml")
                core_xml = read_optional(package, "docProps/core.xml")

                workbook = _parse(workbook_xml, path, "workbook")
                shared = _shared_strings(shared_xml)
                formats = _cell_formats(styles_xml)
                date1904 = _date1904(workbook)
                targets = _sheet_targets(rels_xml)
                sheet_elements = list(workbook.iter(_S + "sheet"))

                pages: list[Page] = []
                sheet_names: list[str] = []
                for index, sheet in enumerate(sheet_elements):
                    name = sheet.get("name") or f"Sheet{index + 1}"
                    sheet_names.append(name)
                    rid = sheet.get(_R + "id") or ""
                    target = targets.get(rid)
                    if not target:
                        pages.append(Page(index=index))
                        continue
                    worksheet_xml = read_optional(package, target)
                    if worksheet_xml is None:
                        pages.append(Page(index=index))
                        continue
                    worksheet = _parse(worksheet_xml, path, name)
                    block = _sheet_table(
                        worksheet,
                        name=name,
                        shared=shared,
                        formats=formats,
                        date1904=date1904,
                    )
                    pages.append(
                        Page(index=index, blocks=[block] if block else [])
                    )
        except zipfile.BadZipFile as exc:
            raise AdapterError(f"cannot read XLSX {path.name!r}: {exc}") from exc
        except OSError as exc:
            raise AdapterError(f"cannot read XLSX {path.name!r}: {exc}") from exc
        except ElementTree.ParseError as exc:
            raise AdapterError(f"cannot parse XLSX {path.name!r}: {exc}") from exc

        return Document(
            path=path,
            kind="xlsx",
            pages=pages,
            meta={
                "sheets": sheet_names,
                "date1904": date1904,
                **core_properties(core_xml),
            },
        )


def _parse(raw: bytes, path: Path, part: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise AdapterError(
            f"cannot parse {part!r} in {path.name!r}: {exc}"
        ) from exc


def _date1904(workbook: ElementTree.Element) -> bool:
    properties = workbook.find(_S + "workbookPr")
    if properties is None:
        return False
    value = properties.get("date1904")
    return value in ("1", "true", "True")


def _sheet_targets(rels_xml: bytes | None) -> dict[str, str]:
    if not rels_xml:
        return {}
    root = ElementTree.fromstring(rels_xml)
    targets: dict[str, str] = {}
    for relationship in root.iter(_REL + "Relationship"):
        rid = relationship.get("Id")
        target = relationship.get("Target")
        if not rid or not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        targets[rid] = path
    return targets


def _shared_strings(raw: bytes | None) -> list[str]:
    if not raw:
        return []
    root = ElementTree.fromstring(raw)
    return [_rich_text(item) for item in root.findall(_S + "si")]


def _rich_text(element: ElementTree.Element) -> str:
    """Concatenate the runs of a shared/inline string, ignoring phonetics."""
    parts: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        for child in node:
            if child.tag == _S + "rPh":
                continue
            if child.tag == _S + "t":
                parts.append(child.text or "")
            else:
                walk(child)

    if element.tag == _S + "t":
        return element.text or ""
    walk(element)
    return "".join(parts)


def _cell_formats(styles_xml: bytes | None) -> list[bool]:
    """Return whether each cellXfs index is a date/time format."""
    if not styles_xml:
        return []
    root = ElementTree.fromstring(styles_xml)
    custom = _custom_formats(root)
    formats: list[bool] = []
    container = root.find(_S + "cellXfs")
    if container is None:
        return formats
    for xf in container.findall(_S + "xf"):
        try:
            format_id = int(xf.get("numFmtId") or 0)
        except ValueError:
            format_id = 0
        formats.append(_is_date_format(format_id, custom))
    return formats


def _is_date_format(format_id: int, custom: dict[int, str]) -> bool:
    if format_id in _DATE_FORMAT_IDS:
        return True
    code = custom.get(format_id)
    if not code:
        return False
    cleaned = _FORMAT_LITERAL.sub("", code).lower()
    return any(char in cleaned for char in ("y", "d", "h", "s"))


def _custom_formats(root: ElementTree.Element) -> dict[int, str]:
    container = root.find(_S + "numFmts")
    if container is None:
        return {}
    out: dict[int, str] = {}
    for fmt in container.findall(_S + "numFmt"):
        try:
            out[int(fmt.get("numFmtId") or -1)] = fmt.get("formatCode") or ""
        except ValueError:
            continue
    return out


def _sheet_table(
    worksheet: ElementTree.Element,
    *,
    name: str,
    shared: list[str],
    formats: list[bool],
    date1904: bool,
) -> Block | None:
    grid: dict[int, dict[int, Block]] = {}
    next_row = 1
    for row_element in worksheet.iter(_S + "row"):
        try:
            row_index = int(row_element.get("r") or next_row)
        except ValueError:
            row_index = next_row
        next_row = row_index + 1
        next_col = 1
        for cell in row_element.findall(_S + "c"):
            reference = cell.get("r") or ""
            column = _column_index(reference) if reference else next_col
            next_col = column + 1
            block = _cell_block(
                cell,
                sheet=name,
                row=row_index,
                column=column,
                shared=shared,
                formats=formats,
                date1904=date1904,
            )
            if block is not None:
                grid.setdefault(row_index, {})[column] = block

    rows = _table_rows(grid, sheet=name)
    if not rows:
        return None
    return Block(
        kind="table",
        text="\n".join(row.text for row in rows),
        children=rows,
        source_ref={"sheet": name, "rows": len(rows)},
    )


def _table_rows(
    grid: dict[int, dict[int, Block]], *, sheet: str
) -> list[Block]:
    if not grid:
        return []
    used_columns = [column for cells in grid.values() for column in cells]
    first_column = min(used_columns)
    last_column = max(used_columns)

    rows: list[Block] = []
    for row_index in sorted(grid):
        cells = grid[row_index]
        last_used = max(cells)
        blocks: list[Block] = []
        for column in range(first_column, last_used + 1):
            block = cells.get(column)
            if block is None:
                block = Block(
                    kind="cell",
                    text="",
                    source_ref={
                        "sheet": sheet,
                        "row": row_index,
                        "col": _column_letter(column),
                    },
                )
            blocks.append(block)
        if not any(block.text for block in blocks):
            continue
        rows.append(
            Block(
                kind="table_row",
                text=" | ".join(block.text for block in blocks),
                children=blocks,
                style={"row": row_index},
                source_ref={"sheet": sheet, "row": row_index},
            )
        )
    return rows


def _cell_block(
    cell: ElementTree.Element,
    *,
    sheet: str,
    row: int,
    column: int,
    shared: list[str],
    formats: list[bool],
    date1904: bool,
) -> Block | None:
    kind = cell.get("t") or "n"
    formula_element = cell.find(_S + "f")
    formula = formula_element.text if formula_element is not None else None
    value_element = cell.find(_S + "v")
    raw = value_element.text if value_element is not None else None

    style_index = _int_or(cell.get("s"), 0)
    is_date = (
        formats[style_index] if 0 <= style_index < len(formats) else False
    )
    style: dict[str, Any] = {}
    if formula:
        style["formula"] = formula
    if kind in ("b", "e"):
        style["type"] = kind
    if is_date:
        style["date"] = True

    if kind == "inlineStr":
        inline = cell.find(_S + "is")
        text = _rich_text(inline) if inline is not None else ""
    else:
        text = _cell_text(
            kind,
            raw,
            shared,
            date1904=date1904,
            is_date=is_date,
        )
    if not text and not formula:
        return None
    if formula and not text:
        text = "=" + formula
    return Block(
        kind="cell",
        text=text,
        style=style,
        source_ref={"sheet": sheet, "row": row, "col": _column_letter(column)},
    )


def _cell_text(
    kind: str,
    raw: str | None,
    shared: list[str],
    *,
    date1904: bool,
    is_date: bool,
) -> str:
    if raw is None:
        return ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if raw.strip() in ("1", "true", "TRUE") else "FALSE"
    if kind in ("str", "e"):
        return raw
    if kind == "d":
        return raw.replace("T", " ").removesuffix("Z")
    try:
        number = float(raw)
    except ValueError:
        return raw
    if is_date:
        return _format_date(number, date1904)
    return _format_number(number)


def _format_number(value: float) -> str:
    if value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    return repr(value)


def _format_date(serial: float, date1904: bool) -> str:
    base = (
        datetime(1904, 1, 1)
        if date1904
        else datetime(1899, 12, 30)  # accounts for Excel's 1900 leap-year bug
    )
    moment = base + timedelta(days=serial)
    moment = moment.replace(microsecond=0)
    if serial < 1:  # time only, e.g. 0.5 -> 12:00
        text = moment.strftime("%H:%M:%S")
        return text.removesuffix(":00")
    if moment.hour or moment.minute or moment.second:
        return moment.isoformat(sep=" ", timespec="seconds")
    return moment.date().isoformat()


def _int_or(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _column_index(reference: str) -> int:
    match = _REF.match(reference)
    letters = match.group(1).upper() if match else "A"
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return index


def _column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters or "A"
