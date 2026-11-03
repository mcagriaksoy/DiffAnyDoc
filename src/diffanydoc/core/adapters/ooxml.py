"""Shared helpers for office open XML packages (DOCX, XLSX).

Both formats are ZIP containers with XML parts. Only the parts needed for
diffing are read, and nothing here depends on a third-party parser.
"""

from __future__ import annotations

import zipfile
from xml.etree import ElementTree

_CORE = "{http://purl.org/dc/elements/1.1/}"
_DCTERMS = "{http://purl.org/dc/terms/}"
_CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"

_FIELDS = {
    "title": _CORE + "title",
    "creator": _CORE + "creator",
    "subject": _CORE + "subject",
    "last_modified_by": _CP + "lastModifiedBy",
    "created": _DCTERMS + "created",
    "modified": _DCTERMS + "modified",
}


def read_optional(package: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        return package.read(name)
    except KeyError:
        return None


def core_properties(raw: bytes | None) -> dict[str, str]:
    """Read docProps/core.xml into a small string-only dictionary."""
    if not raw:
        return {}
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:  # pragma: no cover - defensive
        return {}
    meta: dict[str, str] = {}
    for key, tag in _FIELDS.items():
        value = root.findtext(tag)
        if value and value.strip():
            meta[key] = value.strip()
    return meta
