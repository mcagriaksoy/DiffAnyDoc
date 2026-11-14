"""Pure-stdlib presentation adapter for .pptx (OOXML) and .odp (ODF)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from ..model import Block, Document, Page

_SLIDE_NUM = re.compile(r"ppt/slides/slide(\d+)\.xml$")
_NOTES_NUM = re.compile(r"ppt/notesSlides/notesSlide(\d+)\.xml$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _extract_a_paragraphs(root: ET.Element) -> list[str]:
    """Extract DrawingML (<a:p> -> <a:t>) paragraphs from a slide or notes XML."""
    lines: list[str] = []
    for elem in root.iter():
        if _local(elem.tag) == "p":
            parts = [
                node.text
                for node in elem.iter()
                if _local(node.tag) == "t" and node.text
            ]
            text = "".join(parts).strip()
            if text:
                lines.append(text)
    return lines


def _load_pptx(path: Path) -> list[Page]:
    pages: list[Page] = []
    with zipfile.ZipFile(path, "r") as zf:
        slide_entries: list[tuple[int, str]] = []
        notes_entries: dict[int, str] = {}
        for name in zf.namelist():
            m = _SLIDE_NUM.match(name)
            if m:
                slide_entries.append((int(m.group(1)), name))
                continue
            nm = _NOTES_NUM.match(name)
            if nm:
                notes_entries[int(nm.group(1))] = name

        slide_entries.sort(key=lambda item: item[0])
        for idx, (num, entry) in enumerate(slide_entries):
            root = ET.fromstring(zf.read(entry))
            blocks = [Block(text=line) for line in _extract_a_paragraphs(root)]
            notes_entry = notes_entries.get(num)
            if notes_entry:
                notes_root = ET.fromstring(zf.read(notes_entry))
                for line in _extract_a_paragraphs(notes_root):
                    blocks.append(Block(text=f"[Note] {line}", kind="footnote"))
            pages.append(Page(index=idx, label=f"Slide {idx + 1}", blocks=blocks))
    return pages


def _load_odp(path: Path) -> list[Page]:
    pages: list[Page] = []
    with zipfile.ZipFile(path, "r") as zf:
        if "content.xml" not in zf.namelist():
            return pages
        root = ET.fromstring(zf.read("content.xml"))
        slide_idx = 0
        for elem in root.iter():
            if _local(elem.tag) == "page":
                slide_idx += 1
                blocks: list[Block] = []
                for child in elem.iter():
                    if _local(child.tag) in ("p", "h"):
                        text = "".join(child.itertext()).strip()
                        if text:
                            blocks.append(Block(text=text))
                pages.append(
                    Page(
                        index=slide_idx - 1,
                        label=f"Slide {slide_idx}",
                        blocks=blocks,
                    )
                )
    return pages


class PresentationAdapter:
    """Adapter for PowerPoint (.pptx) and OpenDocument Presentation (.odp)."""

    name = "Presentation"
    extensions = (".pptx", ".odp")

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def load(self, path: Path) -> Document:
        ext = path.suffix.lower()
        pages = _load_pptx(path) if ext == ".pptx" else _load_odp(path)
        return Document(path=path, kind=ext.lstrip("."), pages=pages)
