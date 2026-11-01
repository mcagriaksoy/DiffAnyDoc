"""Adapter registry: file on disk -> :class:`~diffanydoc.core.model.Document`."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..model import Document


class AdapterError(RuntimeError):
    """Raised when a file cannot be turned into a document."""


@runtime_checkable
class Adapter(Protocol):
    name: str
    extensions: tuple[str, ...]

    def supports(self, path: Path) -> bool: ...

    def load(self, path: Path) -> Document: ...


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


def load(path: str | Path) -> Document:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    return adapter_for(path).load(path)
