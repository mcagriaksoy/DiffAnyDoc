"""Report writers."""

from __future__ import annotations

from .html import render_html, write_html_report
from .json import result_to_dict
from .pdf import render_pdf, write_pdf_report

__all__ = [
    "render_html",
    "render_pdf",
    "result_to_dict",
    "write_html_report",
    "write_pdf_report",
]
