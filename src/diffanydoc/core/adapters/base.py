"""Adapter registry: file on disk -> :class:`~diffanydoc.core.model.Document`."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from ..model import Document

OcrMode = Literal["auto", "off", "force"]


class AdapterError(RuntimeError):
    """Raised when a file cannot be turned into a document."""


@dataclass(slots=True, frozen=True)
class LoadOptions:
    """Options that change how a file is read (not how it is compared)."""

    #: "auto": OCR pages without a text layer, "force": OCR every page,
    #: "off": never OCR.
    ocr: OcrMode = "auto"
    #: Tesseract language codes, e.g. "eng+tur". ``None`` picks installed ones.
    ocr_lang: str | None = None
    #: Rendering resolution used for OCR.
    ocr_dpi: int = 300


@runtime_checkable
class Adapter(Protocol):
    name: str
    extensions: tuple[str, ...]

    def supports(self, path: Path) -> bool: ...

    def load(self, path: Path, options: LoadOptions | None = None) -> Document: ...


_REGISTRY: list[Adapter] = []


def register(adapter: Adapter) -> Adapter:
    _REGISTRY.append(adapter)
    return adapter


def adapters() -> list[Adapter]:
    return list(_REGISTRY)


def supported_extensions() -> list[str]:
    return sorted({ext for a in _REGISTRY for ext in a.extensions})


def adapter_for(path: Path) -> Adapter:
    """First registered adapter that claims the file.

    Registration order is significant: specific adapters come before the
    text sniffing fallback.
    """
    path = Path(path)
    for adapter in _REGISTRY:
        if adapter.supports(path):
            return adapter
    raise AdapterError(f"no adapter supports {path.name!r}")


def load(path: str | Path, options: LoadOptions | None = None) -> Document:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_dir():
        raise AdapterError(f"{path.name!r} is a folder, not a file")
    adapter = adapter_for(path)
    # Third-party adapters written against the 0.1 protocol take no options.
    if _accepts_options(adapter):
        return adapter.load(path, options or LoadOptions())
    return adapter.load(path)  # type: ignore[call-arg]


def _accepts_options(adapter: Adapter) -> bool:
    try:
        return len(inspect.signature(adapter.load).parameters) >= 2
    except (TypeError, ValueError):  # pragma: no cover - builtins
        return False
