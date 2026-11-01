"""PDF adapter: text lines with coordinates, using pdfplumber (MIT)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..model import Block, BBox, Document, Page
from ..normalize import join_hyphenated_lines
from .base import AdapterError

#: Words whose vertical centre differs by less than this are on the same line.
_LINE_TOLERANCE_PT = 2.5


class PdfAdapter:
    name = "pdf"
    extensions = (".pdf",)

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def load(self, path: Path) -> Document:
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise AdapterError("pdfplumber is not installed") from exc

        try:
            with pdfplumber.open(str(path)) as pdf:
                meta = _clean_meta(pdf.metadata or {})
                pages = [
                    _build_page(index, page) for index, page in enumerate(pdf.pages)
                ]
        except Exception as exc:  # pdfminer raises a wide range of errors
            raise AdapterError(f"cannot read PDF {path.name!r}: {exc}") from exc

        return Document(path=path, kind="pdf", pages=pages, meta=meta)


def _clean_meta(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in meta.items():
        if value in (None, ""):
            continue
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        out[str(key)] = str(value)
    return out


def _build_page(index: int, page: Any) -> Page:
    words = page.extract_words(
        use_text_flow=False,
        keep_blank_chars=False,
        extra_attrs=["size", "fontname"],
    )
    blocks = _group_lines(words)
    _merge_hyphenation(blocks)
    return Page(
        index=index,
        width=float(page.width),
        height=float(page.height),
        blocks=blocks,
    )


def _group_lines(words: Iterable[dict[str, Any]]) -> list[Block]:
    """Group words into visual lines, keeping bounding boxes."""
    words = sorted(words, key=lambda w: (round(float(w["top"]), 1), float(w["x0"])))
    lines: list[list[dict[str, Any]]] = []
    for word in words:
        if lines:
            current = lines[-1]
            top = sum(float(w["top"]) for w in current) / len(current)
            if abs(float(word["top"]) - top) <= _LINE_TOLERANCE_PT:
                current.append(word)
                continue
        lines.append([word])

    blocks: list[Block] = []
    for line in lines:
        line.sort(key=lambda w: float(w["x0"]))
        blocks.append(
            Block(
                kind="text",
                text=" ".join(str(w["text"]) for w in line),
                bbox=_bbox(line),
                style=_style(line),
                source_ref={"line": len(blocks)},
            )
        )
    return blocks


def _bbox(line: list[dict[str, Any]]) -> BBox:
    return (
        min(float(w["x0"]) for w in line),
        min(float(w["top"]) for w in line),
        max(float(w["x1"]) for w in line),
        max(float(w["bottom"]) for w in line),
    )


def _style(line: list[dict[str, Any]]) -> dict[str, Any]:
    sizes = [float(w.get("size") or 0.0) for w in line]
    fonts = [str(w.get("fontname") or "") for w in line]
    fonts = [f for f in fonts if f]
    font = max(set(fonts), key=fonts.count) if fonts else ""
    return {
        "size": round(sorted(sizes)[len(sizes) // 2], 2),
        "font": font,
        "bold": "bold" in font.lower(),
        "italic": "italic" in font.lower() or "oblique" in font.lower(),
    }


def _merge_hyphenation(blocks: list[Block]) -> None:
    """Join lines that were split by a hyphen at the page edge."""
    texts = join_hyphenated_lines([b.text for b in blocks])
    for block, text in zip(blocks, texts):
        if block.text != text:
            block.text = text
            block.style = {**block.style, "joined_hyphen": True}
