"""Format adapters. Order matters: specific formats first, text fallback last."""

from __future__ import annotations

from .base import (
    Adapter,
    AdapterError,
    adapter_for,
    adapters,
    load,
    register,
    supported_extensions,
)
from .doc import DocAdapter
from .docx import DocxAdapter
from .image import ImageAdapter
from .pdf import PdfAdapter
from .text import TextAdapter
from .xlsx import XlsxAdapter

register(PdfAdapter())
register(DocxAdapter())
register(DocAdapter())
register(XlsxAdapter())
register(ImageAdapter())
register(TextAdapter())

__all__ = [
    "Adapter",
    "AdapterError",
    "adapter_for",
    "adapters",
    "load",
    "register",
    "supported_extensions",
]
