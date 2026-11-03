"""DOCX adapter: paragraphs and tables straight from the OOXML package.

No third-party parser is used. A DOCX file is a ZIP with an XML body
(``word/document.xml``), which is stable enough to read directly for diffing:
we only need text, paragraph order, styles and table cells, not rendering.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree

from ..model import Block, Document, Page
from .base import AdapterError
from .ooxml import core_properties, read_optional

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: XML containers we do not want to read text from.
_SKIP = {
    _W + "pPr",
    _W + "rPr",
    _W + "tblPr",
    _W + "trPr",
    _W + "tcPr",
    _W + "del",  # tracked deletions are no longer part of the document
    _W + "delText",
    _W + "instrText",
}

#: Block-level wrappers whose children are ordinary body content.
_WRAPPERS = {
    _W + "sdt",
    _W + "sdtContent",
    _W + "customXml",
    _W + "ins",
    _W + "smartTag",
}

#: Page break marker used internally while flattening a paragraph.
_PAGE_BREAK = "\f"


class DocxAdapter:
    name = "docx"
    extensions = (".docx",)

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".docx"

    def load(self, path: Path) -> Document:
        try:
            with zipfile.ZipFile(path) as package:
                try:
                    body_xml = package.read("word/document.xml")
                except KeyError as exc:
                    raise AdapterError(
                        f"{path.name!r} is not a Word document (no word/document.xml)"
                    ) from exc
                core_xml = read_optional(package, "docProps/core.xml")
                header_parts = sorted(
                    name
                    for name in package.namelist()
                    if name.startswith("word/header") and name.endswith(".xml")
                )
                footer_parts = sorted(
                    name
                    for name in package.namelist()
                    if name.startswith("word/footer") and name.endswith(".xml")
                )
                note_parts = [
                    name
                    for name in ("word/footnotes.xml", "word/endnotes.xml")
                    if name in package.namelist()
                ]
                headers_xml = [package.read(name) for name in header_parts]
                footers_xml = [package.read(name) for name in footer_parts]
                notes_xml = [package.read(name) for name in note_parts]
        except zipfile.BadZipFile as exc:
            raise AdapterError(f"cannot read DOCX {path.name!r}: {exc}") from exc
        except OSError as exc:
            raise AdapterError(f"cannot read DOCX {path.name!r}: {exc}") from exc

        try:
            root = ElementTree.fromstring(body_xml)
        except ElementTree.ParseError as exc:
            raise AdapterError(
                f"cannot parse DOCX body in {path.name!r}: {exc}"
            ) from exc

        body = root.find(_W + "body")
        if body is None:
            raise AdapterError(f"{path.name!r} has no document body")

        builder = _PageBuilder()
        for raw_part in headers_xml:
            _walk_part(builder, raw_part)
        builder.walk(body)
        for raw_part in notes_xml + footers_xml:
            _walk_part(builder, raw_part)
        builder.finish()

        return Document(
            path=path,
            kind="docx",
            pages=builder.pages,
            meta={**builder.meta, **core_properties(core_xml)},
        )


def _walk_part(builder: "_PageBuilder", raw_xml: bytes) -> None:
    try:
        part_root = ElementTree.fromstring(raw_xml)
    except ElementTree.ParseError:
        return
    for elem in part_root:
        if elem.tag in (_W + "footnote", _W + "endnote"):
            note_type = elem.get(_W + "type") or ""
            if note_type in ("separator", "continuationSeparator"):
                continue
            builder.walk(elem)
        else:
            builder.walk(part_root)
            break


class _PageBuilder:
    """Accumulates blocks into pages, splitting on explicit page breaks."""

    def __init__(self) -> None:
        self.pages: list[Page] = [Page(index=0)]
        self.meta: dict[str, Any] = {"paragraphs": 0, "tables": 0}
        self._table_index = 0

    @property
    def _page(self) -> Page:
        return self.pages[-1]

    def _next_page(self) -> None:
        self.pages.append(Page(index=len(self.pages)))

    def walk(self, container: ElementTree.Element) -> None:
        for child in container:
            tag = child.tag
            if tag in _WRAPPERS:
                self.walk(child)
            elif tag == _W + "p":
                self._add_paragraph(child)
            elif tag == _W + "tbl":
                self._add_table(child)

    def _add_paragraph(self, paragraph: ElementTree.Element) -> None:
        text = "".join(_text_parts(paragraph))
        style = _paragraph_style(paragraph)
        self.meta["paragraphs"] += 1
        for chunk_index, page_chunk in enumerate(text.split(_PAGE_BREAK)):
            if chunk_index:
                self._next_page()
            for line in page_chunk.split("\n"):
                line = line.strip()
                if not line:
                    continue
                self._page.blocks.append(
                    Block(
                        kind="text",
                        text=line,
                        style=dict(style),
                        source_ref={"line": len(self._page.blocks)},
                    )
                )

    def _add_table(self, table: ElementTree.Element) -> None:
        index = self._table_index
        self._table_index += 1
        self.meta["tables"] += 1
        rows: list[Block] = []
        for row_index, row in enumerate(table.findall(_W + "tr")):
            cells: list[Block] = []
            for cell_index, cell in enumerate(row.findall(_W + "tc")):
                lines = _cell_lines(cell)
                cells.append(
                    Block(
                        kind="cell",
                        text=" ".join(lines),
                        children=[
                            Block(kind="text", text=line)
                            for line in lines
                            if line
                        ],
                        source_ref={
                            "table": index,
                            "row": row_index,
                            "col": cell_index,
                        },
                    )
                )
            if not cells:
                continue
            rows.append(
                Block(
                    kind="table_row",
                    text=" | ".join(cell.text for cell in cells),
                    children=cells,
                    style={"header": row_index == 0 and _is_header_row(row)},
                    source_ref={"table": index, "row": row_index},
                )
            )
        if not rows:
            return
        self._page.blocks.append(
            Block(
                kind="table",
                text="\n".join(row.text for row in rows),
                children=rows,
                source_ref={"table": index, "rows": len(rows)},
            )
        )

    def finish(self) -> None:
        # A trailing explicit page break creates an empty page; drop it so the
        # page map does not disagree with what the user sees in Word.
        while len(self.pages) > 1 and not self.pages[-1].blocks:
            self.pages.pop()
        for index, page in enumerate(self.pages):
            page.index = index
        self.meta["pages"] = len(self.pages)


def _text_parts(paragraph: ElementTree.Element) -> Iterator[str]:
    """Yield text pieces of a paragraph in document order."""
    for child in paragraph:
        if child.tag in _SKIP:
            continue
        tag = child.tag
        if tag == _W + "t":
            yield child.text or ""
        elif tag == _W + "tab":
            yield "\t"
        elif tag == _W + "br":
            kind = child.get(_W + "type")
            yield _PAGE_BREAK if kind == "page" else "\n"
        elif tag == _W + "cr":
            yield "\n"
        elif tag == _W + "noBreakHyphen":
            yield "-"
        elif tag == _W + "lastRenderedPageBreak":
            yield _PAGE_BREAK
        elif tag == _W + "softHyphen":
            continue
        else:
            yield from _text_parts(child)


def _paragraph_style(paragraph: ElementTree.Element) -> dict[str, Any]:
    style_name = ""
    properties = paragraph.find(_W + "pPr")
    if properties is not None:
        style = properties.find(_W + "pStyle")
        if style is not None:
            style_name = style.get(_W + "val") or ""
    out: dict[str, Any] = {}
    if style_name:
        out["paragraph_style"] = style_name
        out["heading"] = style_name.lower().startswith("heading")

    bold = False
    italic = False
    underline = False
    strike = False
    sizes: list[float] = []
    fonts: list[str] = []

    for rpr in paragraph.iter(_W + "rPr"):
        if _bool_prop(rpr, _W + "b"):
            bold = True
        if _bool_prop(rpr, _W + "i"):
            italic = True
        u = rpr.find(_W + "u")
        if u is not None and (u.get(_W + "val") or "single") not in ("none", "0", "false"):
            underline = True
        if _bool_prop(rpr, _W + "strike"):
            strike = True
        sz = rpr.find(_W + "sz")
        if sz is not None:
            try:
                sizes.append(float(sz.get(_W + "val") or 0) / 2.0)
            except ValueError:
                pass
        rfonts = rpr.find(_W + "rFonts")
        if rfonts is not None:
            fname = rfonts.get(_W + "ascii") or rfonts.get(_W + "hAnsi") or ""
            if fname:
                fonts.append(fname)

    if bold or out.get("heading"):
        out["bold"] = True
    if italic:
        out["italic"] = True
    if underline:
        out["underline"] = True
    if strike:
        out["strike"] = True
    if sizes:
        out["size"] = round(sorted(sizes)[len(sizes) // 2], 1)
    if fonts:
        out["font"] = max(set(fonts), key=fonts.count)
    return out


def _bool_prop(container: ElementTree.Element, tag: str) -> bool:
    elem = container.find(tag)
    if elem is None:
        return False
    val = (elem.get(_W + "val") or "true").lower()
    return val not in ("0", "false", "off", "none")


def _is_header_row(row: ElementTree.Element) -> bool:
    properties = row.find(_W + "trPr")
    if properties is None:
        return False
    header = properties.find(_W + "tblHeader")
    if header is None:
        return False
    value = header.get(_W + "val")
    return value not in ("false", "0", "off")


def _cell_lines(cell: ElementTree.Element) -> list[str]:
    """Flatten one table cell to text lines (nested tables stay inline)."""
    lines: list[str] = []
    for child in cell:
        if child.tag == _W + "p":
            text = "".join(_text_parts(child)).replace(_PAGE_BREAK, "\n")
            lines.extend(part.strip() for part in text.split("\n"))
        elif child.tag == _W + "tbl":
            for row in child.findall(_W + "tr"):
                cells = [
                    " ".join(filter(None, _cell_lines(tc)))
                    for tc in row.findall(_W + "tc")
                ]
                if any(cells):
                    lines.append(" | ".join(cells))
        elif child.tag in _WRAPPERS:
            lines.extend(_cell_lines(child))
    return [line for line in lines if line]
