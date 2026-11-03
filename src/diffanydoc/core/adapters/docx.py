"""Word (.docx) adapter: reads the OOXML package directly.

Parsing the XML ourselves (instead of python-docx) is what makes these work:

* **tracked changes** — the comparison sees the document as it reads with all
  revisions accepted (``w:ins`` kept, ``w:del`` dropped) and reports how many
  revisions are pending;
* **automatic numbering** — clause numbers ("4.2.") are computed and shown, but
  kept out of the compared text, so inserting a clause does not make every
  following clause look changed;
* **tables** — one block per row with real cells, so the engine can align
  cells instead of comparing a row as one long string;
* headers/footers, footnotes, endnotes, comments and text boxes, each as its
  own section so they never interleave with the body.

The body is one "page" (Word has no fixed pages); the other sections are extra
pages labelled ``section:<name>``.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET

from ..model import Block, Document, Page
from .base import AdapterError, LoadOptions

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DC = "http://purl.org/dc/elements/1.1/"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DCTERMS = "http://purl.org/dc/terms/"


def w(tag: str) -> str:
    return f"{{{W}}}{tag}"


#: Inline containers whose children are runs (or more containers).
_INLINE_CONTAINERS = {
    w("hyperlink"),
    w("smartTag"),
    w("ins"),
    w("moveTo"),
    w("fldSimple"),
    w("customXml"),
    w("bdo"),
    w("dir"),
    w("sdtContent"),
}
#: Content that is not part of the final text.
_SKIP = {w("del"), w("moveFrom"), w("pPr"), w("rPr"), w("sdtPr"), w("sdtEndPr")}

_MAX_XML_BYTES = 200 * 1024 * 1024  # zip-bomb guard


class DocxAdapter:
    name = "docx"
    extensions = (".docx", ".docm", ".dotx", ".dotm")

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def load(self, path: Path, options: LoadOptions | None = None) -> Document:
        try:
            archive = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            if path.suffix.lower() == ".doc":  # pragma: no cover - not registered
                raise AdapterError("legacy .doc files are not supported; save as .docx") from exc
            raise AdapterError(f"cannot read Word file {path.name!r}: {exc}") from exc
        with archive:
            try:
                return _Reader(path, archive).read()
            except AdapterError:
                raise
            except (KeyError, ET.ParseError, ValueError) as exc:
                raise AdapterError(f"cannot read Word file {path.name!r}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Package helpers
# --------------------------------------------------------------------------- #


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > _MAX_XML_BYTES:
        raise AdapterError(f"{name} is too large")
    return ET.fromstring(archive.read(info))


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Relationship id -> (type suffix, target part name)."""
    folder, name = posixpath.split(part)
    root = _xml(archive, posixpath.join(folder, "_rels", name + ".rels"))
    out: dict[str, tuple[str, str]] = {}
    if root is None:
        return out
    for rel in root.findall(f"{{{PKG_REL}}}Relationship"):
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        target = posixpath.normpath(posixpath.join(folder, target)).lstrip("/")
        out[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], target)
    return out


def _on(element: ET.Element | None) -> bool | None:
    """OOXML boolean property: present = on unless w:val says otherwise."""
    if element is None:
        return None
    value = element.get(w("val"))
    return value not in ("0", "false", "off", "none")


# --------------------------------------------------------------------------- #
# Numbering
# --------------------------------------------------------------------------- #


def _roman(number: int) -> str:
    numerals = [
        (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
        (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    ]
    out = []
    for value, letters in numerals:
        while number >= value:
            out.append(letters)
            number -= value
    return "".join(out)


def _letters(number: int) -> str:
    # Word repeats the letter: a..z, aa..zz, ...
    if number <= 0:
        return ""
    letter = chr(ord("a") + (number - 1) % 26)
    return letter * ((number - 1) // 26 + 1)


def _format_number(number: int, fmt: str) -> str:
    if fmt in ("lowerLetter",):
        return _letters(number)
    if fmt in ("upperLetter",):
        return _letters(number).upper()
    if fmt == "lowerRoman":
        return _roman(number)
    if fmt == "upperRoman":
        return _roman(number).upper()
    if fmt in ("decimalZero",):
        return f"{number:02d}"
    if fmt in ("none",):
        return ""
    return str(number)


@dataclass
class _Level:
    start: int = 1
    fmt: str = "decimal"
    text: str = "%1."


@dataclass
class _Numbering:
    #: numId -> (abstractNumId, {ilvl: start override})
    nums: dict[str, tuple[str, dict[int, int]]] = field(default_factory=dict)
    abstract: dict[str, dict[int, _Level]] = field(default_factory=dict)
    counters: dict[str, list[int]] = field(default_factory=dict)

    @classmethod
    def parse(cls, root: ET.Element | None) -> "_Numbering":
        numbering = cls()
        if root is None:
            return numbering
        for abstract in root.findall(w("abstractNum")):
            levels: dict[int, _Level] = {}
            for lvl in abstract.findall(w("lvl")):
                level = _Level()
                start = lvl.find(w("start"))
                if start is not None:
                    level.start = int(start.get(w("val"), "1") or 1)
                fmt = lvl.find(w("numFmt"))
                if fmt is not None:
                    level.fmt = fmt.get(w("val"), "decimal")
                text = lvl.find(w("lvlText"))
                if text is not None:
                    level.text = text.get(w("val"), "")
                levels[int(lvl.get(w("ilvl"), "0"))] = level
            numbering.abstract[abstract.get(w("abstractNumId"), "")] = levels
        for num in root.findall(w("num")):
            ref = num.find(w("abstractNumId"))
            overrides: dict[int, int] = {}
            for override in num.findall(w("lvlOverride")):
                start = override.find(w("startOverride"))
                if start is not None:
                    overrides[int(override.get(w("ilvl"), "0"))] = int(start.get(w("val"), "1"))
            if ref is not None:
                numbering.nums[num.get(w("numId"), "")] = (ref.get(w("val"), ""), overrides)
        return numbering

    def label(self, num_id: str, ilvl: int) -> str | None:
        if num_id in ("", "0") or num_id not in self.nums:
            return None
        abstract_id, overrides = self.nums[num_id]
        levels = self.abstract.get(abstract_id, {})
        level = levels.get(ilvl)
        if level is None:
            return None
        counters = self.counters.setdefault(num_id, [0] * 9)
        if ilvl >= len(counters):
            return None
        if counters[ilvl] == 0:
            counters[ilvl] = overrides.get(ilvl, level.start)
        else:
            counters[ilvl] += 1
        for deeper in range(ilvl + 1, len(counters)):
            counters[deeper] = 0
        if level.fmt == "bullet":
            return "•"

        def replace(match: re.Match[str]) -> str:
            index = int(match.group(1)) - 1
            ref = levels.get(index, _Level())
            value = counters[index] if index < len(counters) else 0
            if value == 0:
                value = overrides.get(index, ref.start)
            return _format_number(value, ref.fmt)

        return re.sub(r"%([1-9])", replace, level.text).strip() or None


# --------------------------------------------------------------------------- #
# Reader
# --------------------------------------------------------------------------- #


@dataclass
class _Paragraph:
    text: str
    marks: list[list[Any]]
    style: str | None
    heading: int | None
    list_label: str | None
    floating: list["_Paragraph"]


class _Reader:
    def __init__(self, path: Path, archive: zipfile.ZipFile) -> None:
        self.path = path
        self.archive = archive
        self.styles: dict[str, dict[str, Any]] = {}
        self.numbering = _Numbering()
        self.footnote_numbers: dict[tuple[str, str], int] = {}
        self.tracked = {"insertions": 0, "deletions": 0, "moves": 0}
        self.table_count = 0
        self.textbox_count = 0

    # -- top level -------------------------------------------------------- #

    def read(self) -> Document:
        main = self._main_part()
        body_root = _xml(self.archive, main)
        if body_root is None:
            raise AdapterError(f"{self.path.name!r} has no document body")
        self._read_styles()
        self.numbering = _Numbering.parse(_xml(self.archive, "word/numbering.xml"))
        rels = _rels(self.archive, main)

        body = body_root.find(w("body"))
        pages: list[Page] = []
        body_blocks = list(self._blocks(body if body is not None else body_root))
        self._count_revisions(body_root)
        pages.append(Page(index=0, blocks=body_blocks, label="section:body"))

        header_blocks = self._header_footer_blocks(rels)
        if header_blocks:
            pages.append(Page(index=len(pages), blocks=header_blocks, label="section:headers"))

        for kind, element_name in (("footnotes", "footnote"), ("endnotes", "endnote")):
            blocks = self._notes(rels, kind, element_name)
            if blocks:
                pages.append(Page(index=len(pages), blocks=blocks, label=f"section:{kind}"))

        comments = self._comments(rels)
        if comments:
            pages.append(Page(index=len(pages), blocks=comments, label="section:comments"))

        meta = self._core_properties()
        meta["tables"] = self.table_count
        if self.textbox_count:
            meta["text_boxes"] = self.textbox_count
        document = Document(path=self.path, kind="docx", pages=pages, meta=meta)
        if any(self.tracked.values()):
            meta["tracked_changes"] = {k: v for k, v in self.tracked.items() if v}
            document.warnings.append({"code": "tracked_changes", **self.tracked})
        if not any(page.blocks for page in pages):
            document.warnings.append({"code": "empty_document"})
        return document

    def _main_part(self) -> str:
        root = _rels(self.archive, "")
        for _, (kind, target) in root.items():
            if kind == "officeDocument":
                return target
        return "word/document.xml"

    def _read_styles(self) -> None:
        root = _xml(self.archive, "word/styles.xml")
        if root is None:
            return
        for style in root.findall(w("style")):
            style_id = style.get(w("styleId"), "")
            name_el = style.find(w("name"))
            name = name_el.get(w("val"), style_id) if name_el is not None else style_id
            info: dict[str, Any] = {"name": name}
            ppr = style.find(w("pPr"))
            if ppr is not None:
                outline = ppr.find(w("outlineLvl"))
                if outline is not None:
                    info["outline"] = int(outline.get(w("val"), "9"))
                numpr = ppr.find(w("numPr"))
                if numpr is not None:
                    info["numPr"] = numpr
            based = style.find(w("basedOn"))
            if based is not None:
                info["basedOn"] = based.get(w("val"))
            match = re.match(r"(?i)heading\s*(\d)$", name) or re.match(r"(?i)title$", name)
            if match:
                info["heading"] = int(match.group(1)) if match.groups() else 0
            self.styles[style_id] = info

    def _style_value(self, style_id: str | None, key: str) -> Any:
        seen = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            info = self.styles.get(style_id)
            if info is None:
                return None
            if key in info:
                return info[key]
            style_id = info.get("basedOn")
        return None

    def _count_revisions(self, root: ET.Element) -> None:
        for element in root.iter():
            if element.tag == w("ins"):
                self.tracked["insertions"] += 1
            elif element.tag == w("del"):
                self.tracked["deletions"] += 1
            elif element.tag in (w("moveFrom"),):
                self.tracked["moves"] += 1

    def _core_properties(self) -> dict[str, Any]:
        root = _xml(self.archive, "docProps/core.xml")
        meta: dict[str, Any] = {}
        if root is None:
            return meta
        for key, tag in (
            ("title", f"{{{DC}}}title"),
            ("author", f"{{{DC}}}creator"),
            ("last_modified_by", f"{{{CP}}}lastModifiedBy"),
            ("revision", f"{{{CP}}}revision"),
            ("created", f"{{{DCTERMS}}}created"),
            ("modified", f"{{{DCTERMS}}}modified"),
        ):
            element = root.find(tag)
            if element is not None and (element.text or "").strip():
                meta[key] = element.text.strip()
        return meta

    # -- sections ---------------------------------------------------------- #

    def _header_footer_blocks(self, rels: dict[str, tuple[str, str]]) -> list[Block]:
        blocks: list[Block] = []
        seen: set[str] = set()
        for kind in ("header", "footer"):
            for _, (rel_type, target) in sorted(rels.items(), key=lambda item: item[1][1]):
                if rel_type != kind:
                    continue
                root = _xml(self.archive, target)
                if root is None:
                    continue
                for block in self._blocks(root):
                    # The same header is usually repeated per section and for
                    # first/even pages; compare each distinct line once.
                    key = f"{kind}:{block.text}"
                    if key in seen:
                        continue
                    seen.add(key)
                    block.style = {**block.style, "part": kind}
                    blocks.append(block)
        return blocks

    def _notes(self, rels: dict[str, tuple[str, str]], kind: str, element_name: str) -> list[Block]:
        target = next((t for r, t in rels.values() if r == kind), None)
        root = _xml(self.archive, target) if target else None
        if root is None:
            return []
        blocks: list[Block] = []
        for note in root.findall(w(element_name)):
            if note.get(w("type")) in ("separator", "continuationSeparator", "continuationNotice"):
                continue
            note_id = note.get(w("id"), "")
            number = self.footnote_numbers.get((element_name, note_id))
            text_blocks = list(self._blocks(note))
            if not text_blocks:
                continue
            prefix = f"[{number}]" if number else f"[{element_name[0]}{note_id}]"
            text_blocks[0].style = {**text_blocks[0].style, "list": prefix}
            blocks.extend(text_blocks)
        return blocks

    def _comments(self, rels: dict[str, tuple[str, str]]) -> list[Block]:
        target = next((t for r, t in rels.values() if r == "comments"), None)
        root = _xml(self.archive, target) if target else None
        if root is None:
            return []
        blocks: list[Block] = []
        for comment in root.findall(w("comment")):
            author = comment.get(w("author"), "")
            text = " ".join(b.text for b in self._blocks(comment) if b.text)
            if not text:
                continue
            blocks.append(
                Block(
                    kind="text",
                    text=text,
                    style={"list": f"{author}:" if author else None, "part": "comment"},
                    source_ref={"comment": comment.get(w("id"))},
                )
            )
        return blocks

    # -- block level ------------------------------------------------------- #

    def _blocks(self, container: ET.Element) -> Iterator[Block]:
        for child in container:
            tag = child.tag
            if tag == w("p"):
                yield from self._paragraph_blocks(child)
            elif tag == w("tbl"):
                yield from self._table(child)
            elif tag in (w("sdt"), w("customXml"), w("sdtContent")):
                inner = child.find(w("sdtContent")) if tag == w("sdt") else child
                if inner is not None:
                    yield from self._blocks(inner)
            elif tag == f"{{{MC}}}AlternateContent":
                choice = child.find(f"{{{MC}}}Choice")
                if choice is not None:
                    yield from self._blocks(choice)
            elif tag in (w("ins"), w("moveTo")):
                yield from self._blocks(child)

    def _paragraph_blocks(self, element: ET.Element) -> Iterator[Block]:
        paragraph = self._paragraph(element)
        if paragraph.text.strip():
            style: dict[str, Any] = {"marks": paragraph.marks}
            if paragraph.style:
                style["style"] = paragraph.style
            if paragraph.heading is not None:
                style["heading"] = paragraph.heading
            if paragraph.list_label:
                style["list"] = paragraph.list_label
            if paragraph.marks and _covers(paragraph.marks, len(paragraph.text), "bold"):
                style["bold"] = True
            if paragraph.marks and _covers(paragraph.marks, len(paragraph.text), "italic"):
                style["italic"] = True
            yield Block(kind="text", text=paragraph.text, style=style)
        for floating in paragraph.floating:
            if floating.text.strip():
                yield Block(
                    kind="text",
                    text=floating.text,
                    style={"marks": floating.marks, "part": "textbox"},
                )

    def _paragraph(self, element: ET.Element) -> _Paragraph:
        ppr = element.find(w("pPr"))
        style_id = None
        num_id = None
        ilvl = 0
        outline = None
        if ppr is not None:
            pstyle = ppr.find(w("pStyle"))
            if pstyle is not None:
                style_id = pstyle.get(w("val"))
            numpr = ppr.find(w("numPr"))
            if numpr is not None:
                num_id, ilvl = _num_pr(numpr)
            outline_el = ppr.find(w("outlineLvl"))
            if outline_el is not None:
                outline = int(outline_el.get(w("val"), "9"))
        if num_id is None and style_id:
            style_numpr = self._style_value(style_id, "numPr")
            if style_numpr is not None:
                num_id, ilvl = _num_pr(style_numpr)

        heading = self._style_value(style_id, "heading") if style_id else None
        if heading is None:
            if outline is None and style_id:
                outline = self._style_value(style_id, "outline")
            if outline is not None and outline < 9:
                heading = outline + 1

        parts: list[str] = []
        marks: list[list[Any]] = []
        floating: list[_Paragraph] = []
        self._inline(element, parts, marks, floating)
        text = "".join(parts)
        # Collapse the internal whitespace that runs/tabs leave behind, but
        # keep the text otherwise exact (normalisation happens in the engine).
        list_label = self.numbering.label(num_id, ilvl) if num_id and text.strip() else None
        name = self.styles.get(style_id or "", {}).get("name") if style_id else None
        return _Paragraph(
            text=text,
            marks=marks,
            style=name,
            heading=heading,
            list_label=list_label,
            floating=floating,
        )

    def _inline(
        self,
        element: ET.Element,
        parts: list[str],
        marks: list[list[Any]],
        floating: list[_Paragraph],
    ) -> None:
        for child in element:
            tag = child.tag
            if tag in _SKIP:
                continue
            if tag == w("r"):
                self._run(child, parts, marks, floating)
            elif tag in _INLINE_CONTAINERS:
                self._inline(child, parts, marks, floating)
            elif tag == w("sdt"):
                content = child.find(w("sdtContent"))
                if content is not None:
                    self._inline(content, parts, marks, floating)
            elif tag == f"{{{MC}}}AlternateContent":
                choice = child.find(f"{{{MC}}}Choice")
                if choice is not None:
                    self._inline(choice, parts, marks, floating)

    def _run(
        self,
        run: ET.Element,
        parts: list[str],
        marks: list[list[Any]],
        floating: list[_Paragraph],
    ) -> None:
        rpr = run.find(w("rPr"))
        flags: list[str] = []
        if rpr is not None:
            if _on(rpr.find(w("vanish"))):
                return  # hidden text is not part of what the reader sees
            for flag, tag in (("bold", "b"), ("italic", "i"), ("strike", "strike")):
                if _on(rpr.find(w(tag))):
                    flags.append(flag)
            underline = rpr.find(w("u"))
            if underline is not None and underline.get(w("val"), "single") != "none":
                flags.append("underline")
            rstyle = rpr.find(w("rStyle"))
            if rstyle is not None:
                flags.append("style:" + rstyle.get(w("val"), ""))
        start = sum(len(p) for p in parts)
        for child in run:
            tag = child.tag
            if tag == w("t"):
                parts.append(child.text or "")
            elif tag == w("tab"):
                parts.append("\t")
            elif tag in (w("br"), w("cr")):
                parts.append(" ")
            elif tag == w("noBreakHyphen"):
                parts.append("-")
            elif tag == w("sym"):
                code = child.get(w("char"), "")
                try:
                    value = int(code, 16)
                    # Symbol fonts map into the private-use area (F0xx).
                    parts.append(chr(value - 0xF000 if value >= 0xF000 else value))
                except ValueError:
                    pass
            elif tag in (w("footnoteReference"), w("endnoteReference")):
                kind = "footnote" if tag == w("footnoteReference") else "endnote"
                key = (kind, child.get(w("id"), ""))
                number = self.footnote_numbers.setdefault(
                    key, sum(1 for k in self.footnote_numbers if k[0] == kind) + 1
                )
                parts.append(f"[{number}]")
            elif tag in (w("drawing"), w("pict"), f"{{{MC}}}AlternateContent"):
                self._textboxes(child, floating)
        end = sum(len(p) for p in parts)
        if flags and end > start:
            marks.append([start, end, sorted(flags)])

    def _textboxes(self, element: ET.Element, floating: list[_Paragraph]) -> None:
        for fallback in element.iter(f"{{{MC}}}Fallback"):
            # VML duplicate of the same text box: drop it.
            fallback.clear()
        for box in element.iter(w("txbxContent")):
            self.textbox_count += 1
            for paragraph in box.iter(w("p")):
                floating.append(self._paragraph(paragraph))

    def _table(self, table: ET.Element) -> Iterator[Block]:
        self.table_count += 1
        number = self.table_count
        row_number = 0
        for row in table.findall(w("tr")):
            cells: list[str] = []
            nested: list[Block] = []
            for cell in row.findall(w("tc")):
                tcpr = cell.find(w("tcPr"))
                span = 1
                continuation = False
                if tcpr is not None:
                    grid = tcpr.find(w("gridSpan"))
                    if grid is not None:
                        span = max(1, int(grid.get(w("val"), "1") or 1))
                    vmerge = tcpr.find(w("vMerge"))
                    if vmerge is not None and vmerge.get(w("val"), "continue") == "continue":
                        continuation = True
                texts: list[str] = []
                for block in self._blocks(cell):
                    if block.cells is not None:
                        nested.append(block)
                        texts.append(" ".join(block.cells))
                    else:
                        prefix = block.style.get("list")
                        texts.append(f"{prefix} {block.text}" if prefix and prefix != "•" else block.text)
                value = "" if continuation else " ".join(t.strip() for t in texts if t.strip())
                cells.append(value)
                # Spanned cells keep the column grid aligned across rows.
                cells.extend([""] * (span - 1))
            while cells and not cells[-1]:
                cells.pop()
            if not any(c.strip() for c in cells):
                continue
            row_number += 1
            if len(cells) == 1:
                # Single-column layout tables are really just paragraphs.
                yield Block(kind="text", text=cells[0], style={"table": number})
                continue
            yield Block(
                kind="text",
                text=" | ".join(cells),
                cells=cells,
                style={"table": number, "row": row_number},
                label=f"T{number}",
            )


def _num_pr(numpr: ET.Element) -> tuple[str | None, int]:
    num = numpr.find(w("numId"))
    lvl = numpr.find(w("ilvl"))
    num_id = num.get(w("val")) if num is not None else None
    ilvl = int(lvl.get(w("val"), "0")) if lvl is not None else 0
    return num_id, ilvl


def _covers(marks: list[list[Any]], length: int, flag: str) -> bool:
    covered = sum(end - start for start, end, flags in marks if flag in flags)
    return length > 0 and covered >= length * 0.95
