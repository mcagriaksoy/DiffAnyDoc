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
from .pdf import PdfAdapter
from .text import TextAdapter

register(PdfAdapter())
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
