"""Comparison engine."""

from __future__ import annotations

from .align import align_pages
from .engine import (
    DiffOptions,
    compare,
    compare_documents,
    fold_equal_runs,
    result_as_dict,
    supported_formats,
)
from .geometry import change_rects
from .lines import cell_diff, document_lines, format_changes, inline_diff, line_similarity

__all__ = [
    "DiffOptions",
    "align_pages",
    "cell_diff",
    "change_rects",
    "compare",
    "compare_documents",
    "document_lines",
    "fold_equal_runs",
    "format_changes",
    "inline_diff",
    "line_similarity",
    "result_as_dict",
    "supported_formats",
]
