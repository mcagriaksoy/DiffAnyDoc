"""Plain-text adapter, also used as the fallback for unknown-but-textual files."""

from __future__ import annotations

from pathlib import Path

from ..model import Block, Document, Page
from .base import AdapterError

_TEXT_EXTENSIONS = (
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".ts",
    ".py",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".rs",
    ".go",
    ".sh",
    ".sql",
)

#: BOM-sensitive, then common encodings in order of likelihood.
_ENCODINGS = ("utf-8-sig", "utf-16", "cp1254", "cp1252", "latin-1")


class TextAdapter:
    name = "text"
    extensions = _TEXT_EXTENSIONS

    def supports(self, path: Path) -> bool:
        if path.suffix.lower() in self.extensions:
            return True
        # Unknown extension: accept it if the first block looks like text.
        return _looks_textual(path)

    def load(self, path: Path) -> Document:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AdapterError(f"cannot read {path.name!r}: {exc}") from exc

        text, encoding = _decode(raw)
        blocks = [
            Block(kind="text", text=line, source_ref={"line": number})
            for number, line in enumerate(text.splitlines())
        ]
        page = Page(index=0, blocks=blocks)
        return Document(
            path=path,
            kind="text",
            pages=[page],
            meta={"encoding": encoding, "bytes": len(raw)},
        )


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8/replace"


def _looks_textual(path: Path, sample: int = 4096) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(sample)
    except OSError:
        return False
    if not chunk:
        return True
    if b"\x00" in chunk and not chunk.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    printable = sum(
        1 for byte in chunk if 9 <= byte <= 13 or 32 <= byte <= 126 or byte >= 128
    )
    return printable / len(chunk) > 0.85
