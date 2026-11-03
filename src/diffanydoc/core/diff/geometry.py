"""Where the changes are on the page: rectangles for the page overlay.

Each changed row yields

* ``level="line"`` boxes: the visual lines the row occupies (a reflowed
  paragraph spans several lines, possibly two pages), and
* ``level="word"`` boxes for paired rows: only the words that changed, found
  by mapping the inline segments back onto the per-word spans.

Coordinates are in page units (PDF points, image pixels).
"""

from __future__ import annotations

from typing import Any

from ..layout import union
from ..model import DiffResult, Line, Segment, Span


def _changed_ranges(segments: list[Segment] | None, side: str) -> list[tuple[int, int]]:
    if not segments:
        return []
    wanted = "delete" if side == "left" else "insert"
    ranges: list[tuple[int, int]] = []
    offset = 0
    for segment in segments:
        end = offset + len(segment.text)
        if segment.kind == wanted and segment.text.strip():
            ranges.append((offset, end))
        offset = end
    return ranges


def _visual_lines(spans: list[Span]) -> list[tuple[int, tuple[float, float, float, float]]]:
    """Group word spans into visual lines: (page, box)."""
    groups: list[list[Span]] = []
    for span in spans:
        if groups:
            last = groups[-1][-1]
            height = max(last.bbox[3] - last.bbox[1], 1.0)
            same_line = (
                span.page == last.page
                and abs(span.bbox[1] - last.bbox[1]) < 0.6 * height
                and span.bbox[0] >= last.bbox[0] - 1
            )
            if same_line:
                groups[-1].append(span)
                continue
        groups.append([span])
    out = []
    for group in groups:
        box = union(s.bbox for s in group)
        if box is not None:
            out.append((group[0].page, box))
    return out


def _rect(page: int, box: Any, kind: str, level: str, row: int, text: str) -> dict[str, Any]:
    return {
        "page": page,
        "x0": round(box[0], 2),
        "top": round(box[1], 2),
        "x1": round(box[2], 2),
        "bottom": round(box[3], 2),
        "kind": kind,
        "level": level,
        "row": row,
        "text": text,
    }


def line_rects(line: Line, kind: str, row: int, inline: list[Segment] | None, side: str) -> list[dict[str, Any]]:
    rects: list[dict[str, Any]] = []
    if line.spans:
        for page, box in _visual_lines(line.spans):
            rects.append(_rect(page, box, kind, "line", row, line.text))
        for start, end in _changed_ranges(inline, side):
            words = [s for s in line.spans if s.start < end and s.end > start]
            for page, box in _visual_lines(words):
                rects.append(_rect(page, box, kind, "word", row, line.text[start:end]))
    elif line.bbox is not None:
        rects.append(_rect(line.page, line.bbox, kind, "line", row, line.text))
    return rects


def change_rects(result: DiffResult) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Per side, per page index (as string): the overlay rectangles."""
    out: dict[str, dict[str, list[dict[str, Any]]]] = {"left": {}, "right": {}}
    for index, row in enumerate(result.rows):
        if row.kind == "equal" and not row.format_changes:
            continue
        kind = "format" if row.kind == "equal" else row.kind
        for side in ("left", "right"):
            line = row.left if side == "left" else row.right
            if line is None:
                continue
            inline = row.left_inline if side == "left" else row.right_inline
            for rect in line_rects(line, kind, index, inline if row.kind == "replace" else None, side):
                out[side].setdefault(str(rect.pop("page")), []).append(rect)
    return out
