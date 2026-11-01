"""Machine-readable report: stable JSON, used by the API and golden tests."""

from __future__ import annotations

from typing import Any

from ..model import DiffResult, Line, Row, Segment


def _line_to_dict(line: Line, number: int) -> dict[str, Any]:
    return {
        "text": line.text,
        "page": line.page,
        "bbox": list(line.bbox) if line.bbox else None,
        "number": number,
        "style": line.style or None,
    }


def _segments_to_dict(segments: list[Segment] | None) -> list[dict[str, str]] | None:
    if segments is None:
        return None
    return [{"kind": segment.kind, "text": segment.text} for segment in segments]


def result_to_dict(result: DiffResult, *, include_pages: bool = False) -> dict[str, Any]:
    left_number = 0
    right_number = 0
    rows: list[dict[str, Any]] = []

    for row in result.rows:
        left = right = None
        if row.left is not None:
            left_number += 1
            left = _line_to_dict(row.left, left_number)
        if row.right is not None:
            right_number += 1
            right = _line_to_dict(row.right, right_number)
        rows.append(
            {
                "kind": row.kind,
                "hidden_before": row.hidden_before,
                "left": left,
                "right": right,
                "left_inline": _segments_to_dict(row.left_inline),
                "right_inline": _segments_to_dict(row.right_inline),
            }
        )

    return {
        "left": {
            "path": str(result.left_path),
            "name": result.left_path.name,
            "kind": result.left_kind,
            "pages": _page_count(result, "left"),
        },
        "right": {
            "path": str(result.right_path),
            "name": result.right_path.name,
            "kind": result.right_kind,
            "pages": _page_count(result, "right"),
        },
        "identical": result.identical,
        "stats": result.stats.as_dict(),
        "page_map": [
            {"left": pair.left, "right": pair.right, "similarity": pair.similarity}
            for pair in result.page_map
        ],
        "options": result.options,
        "rows": rows,
    }


def _page_count(result: DiffResult, side: str) -> int:
    indexes = {
        getattr(row.left if side == "left" else row.right, "page", None)
        for row in result.rows
        if (row.left if side == "left" else row.right) is not None
    }
    indexes.discard(None)
    return max(indexes) + 1 if indexes else 0


def row_label(row: Row) -> str:
    return {
        "equal": " ",
        "insert": "+",
        "delete": "-",
        "replace": "~",
    }[row.kind]
