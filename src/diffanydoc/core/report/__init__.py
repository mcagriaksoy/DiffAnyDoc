"""Report writers."""

from __future__ import annotations

from .html import render_html, write_html_report
from .json import result_to_dict

__all__ = ["render_html", "result_to_dict", "write_html_report"]
