"""Comparison engine."""

from __future__ import annotations

from .align import align_pages
from .engine import (
    DiffOptions,
    compare,
    file_sha256,
    preload_document,
    result_as_dict,
    supported_formats,
)
from .lines import document_lines, inline_diff, line_similarity

__all__ = [
    "DiffOptions",
    "align_pages",
    "compare",
    "document_lines",
    "file_sha256",
    "inline_diff",
    "line_similarity",
    "preload_document",
    "result_as_dict",
    "supported_formats",
]
