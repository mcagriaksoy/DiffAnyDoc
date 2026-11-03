"""Machine-readable report: stable JSON, used by the API and golden tests.

The format is additive: keys are only ever added, so scripts written against
an older version keep working.
"""

from __future__ import annotations

from typing import Any

from ..model import CellDiff, DiffResult, DocumentInfo, Line, Row, Segment, VisualPage

FORMAT_VERSION = 2


def _line_to_dict(line: Line) -> dict[str, Any]:
    style = {
        key: value
        for key, value in (line.style or {}).items()
        # Internal formatting runs are large and only used for comparison.
        if key not in ("marks",)
    }
    return {
        "text": line.text,
        "page": line.page,
        "bbox": list(line.bbox) if line.bbox else None,
        "number": line.number,
        "label": line.label,
        "cells": line.cells,
        "style": style or None,
    }


def _segments_to_dict(segments: list[Segment] | None) -> list[dict[str, str]] | None:
    if segments is None:
        return None
    return [{"kind": segment.kind, "text": segment.text} for segment in segments]


def _cell_to_dict(cell: CellDiff) -> dict[str, Any]:
    return {
        "kind": cell.kind,
        "left": cell.left,
        "right": cell.right,
        "left_inline": _segments_to_dict(cell.left_inline),
        "right_inline": _segments_to_dict(cell.right_inline),
        "left_column": cell.left_column,
        "right_column": cell.right_column,
    }


def row_to_dict(row: Row) -> dict[str, Any]:
    return {
        "kind": row.kind,
        "hidden_before": row.hidden_before,
        "left": _line_to_dict(row.left) if row.left is not None else None,
        "right": _line_to_dict(row.right) if row.right is not None else None,
        "left_inline": _segments_to_dict(row.left_inline),
        "right_inline": _segments_to_dict(row.right_inline),
        "cells": [_cell_to_dict(c) for c in row.cells] if row.cells is not None else None,
        "format_changes": row.format_changes,
    }


def visual_page_to_dict(page: VisualPage) -> dict[str, Any]:
    return {
        "pair": page.pair,
        "left": page.left,
        "right": page.right,
        "identical": page.identical,
        "changed_ratio": page.changed_ratio,
        "offset": list(page.offset),
        "scaled": page.scaled,
        "regions": [
            {
                "x0": r.x0,
                "top": r.top,
                "x1": r.x1,
                "bottom": r.bottom,
                "kind": r.kind,
                "density": r.density,
            }
            for r in page.regions
        ],
    }


def _side(result: DiffResult, side: str) -> dict[str, Any]:
    info: DocumentInfo | None = result.left_info if side == "left" else result.right_info
    path = result.left_path if side == "left" else result.right_path
    kind = result.left_kind if side == "left" else result.right_kind
    out: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "kind": kind,
        "pages": len(info.pages) if info else _page_count(result, side),
    }
    if info is not None:
        out["sha256"] = info.sha256 or None
        out["meta"] = info.meta
        out["warnings"] = info.warnings
        out["renderable"] = info.renderable
        out["page_info"] = info.pages
    return out


def result_to_dict(result: DiffResult, *, include_pages: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "format": FORMAT_VERSION,
        "left": _side(result, "left"),
        "right": _side(result, "right"),
        "identical": result.identical,
        "text_identical": result.text_identical,
        "byte_identical": result.byte_identical,
        "stats": result.stats.as_dict(),
        "page_map": [
            {"left": pair.left, "right": pair.right, "similarity": round(pair.similarity, 4)}
            for pair in result.page_map
        ],
        "options": result.options,
        "rows": [row_to_dict(row) for row in result.rows],
        "visual": (
            [visual_page_to_dict(page) for page in result.visual]
            if result.visual is not None
            else None
        ),
    }
    return payload


def _page_count(result: DiffResult, side: str) -> int:
    indexes = {
        getattr(row.left if side == "left" else row.right, "page", None)
        for row in result.rows
        if (row.left if side == "left" else row.right) is not None
    }
    indexes.discard(None)
    return max(indexes) + 1 if indexes else 0  # type: ignore[type-var]


def row_label(row: Row) -> str:
    return {
        "equal": " ",
        "insert": "+",
        "delete": "-",
        "replace": "~",
    }[row.kind]
