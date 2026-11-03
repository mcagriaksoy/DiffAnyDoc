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
    table_blocks, table_boxes = _extract_tables(page)
    if table_boxes:
        words = [w for w in words if not _word_in_any_box(w, table_boxes)]

    text_blocks = _group_lines(words)
    _merge_hyphenation(text_blocks)
    blocks = _interleave_by_vertical_order(text_blocks, table_blocks)

    for img in getattr(page, "images", None) or ():
        try:
            x0 = float(img.get("x0", 0.0))
            top = float(img.get("top", 0.0))
            x1 = float(img.get("x1", 0.0))
            bottom = float(img.get("bottom", 0.0))
        except (TypeError, ValueError):
            continue
        if x1 > x0 and bottom > top:
            blocks.append(
                Block(
                    kind="image",
                    text="",
                    bbox=(x0, top, x1, bottom),
                    source_ref={"name": str(img.get("name") or "")},
                )
            )
    return Page(
        index=index,
        width=float(page.width),
        height=float(page.height),
        blocks=blocks,
    )


def _extract_tables(page: Any) -> tuple[list[Block], list[BBox]]:
    """Extract ruled/bordered tables on a PDF page into structural table blocks."""
    try:
        found = page.find_tables() or []
    except Exception:
        return [], []

    blocks: list[Block] = []
    boxes: list[BBox] = []
    for tbl_index, tbl in enumerate(found):
        try:
            bbox_raw = tbl.bbox
            t_bbox: BBox = (
                float(bbox_raw[0]),
                float(bbox_raw[1]),
                float(bbox_raw[2]),
                float(bbox_raw[3]),
            )
            raw_rows = tbl.extract() or []
        except Exception:
            continue

        row_blocks: list[Block] = []
        row_objs = getattr(tbl, "rows", None) or ()
        for r_idx, raw_row in enumerate(raw_rows):
            if not raw_row:
                continue
            cells: list[Block] = []
            for c_idx, cell_val in enumerate(raw_row):
                cleaned = " ".join(str(cell_val or "").split())
                cells.append(
                    Block(
                        kind="cell",
                        text=cleaned,
                        source_ref={
                            "table": tbl_index,
                            "row": r_idx,
                            "col": c_idx,
                        },
                    )
                )
            if not any(c.text for c in cells):
                continue
            r_bbox: BBox | None = None
            if r_idx < len(row_objs) and getattr(row_objs[r_idx], "bbox", None):
                rb = row_objs[r_idx].bbox
                r_bbox = (float(rb[0]), float(rb[1]), float(rb[2]), float(rb[3]))
            row_blocks.append(
                Block(
                    kind="table_row",
                    text=" | ".join(c.text for c in cells),
                    bbox=r_bbox or t_bbox,
                    children=cells,
                    style={"header": r_idx == 0},
                    source_ref={"table": tbl_index, "row": r_idx},
                )
            )
        if len(row_blocks) >= 1 and any(len(r.children) >= 2 for r in row_blocks):
            blocks.append(
                Block(
                    kind="table",
                    text="\n".join(r.text for r in row_blocks),
                    bbox=t_bbox,
                    children=row_blocks,
                    source_ref={"table": tbl_index, "rows": len(row_blocks)},
                )
            )
            boxes.append(t_bbox)
    return blocks, boxes


def _word_in_any_box(word: dict[str, Any], boxes: list[BBox]) -> bool:
    try:
        cx = (float(word["x0"]) + float(word["x1"])) / 2.0
        cy = (float(word["top"]) + float(word["bottom"])) / 2.0
    except (KeyError, TypeError, ValueError):
        return False
    return any(
        (b[0] - 1.5) <= cx <= (b[2] + 1.5) and (b[1] - 1.5) <= cy <= (b[3] + 1.5)
        for b in boxes
    )


def _interleave_by_vertical_order(
    text_blocks: list[Block], table_blocks: list[Block]
) -> list[Block]:
    if not table_blocks:
        return text_blocks
    combined = text_blocks + table_blocks
    combined.sort(key=lambda b: b.bbox[1] if b.bbox else 0.0)
    return combined


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
