"""Plain-text adapter, also used as the fallback for unknown-but-textual files."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from ..model import Block, Document, Page
from .base import AdapterError, LoadOptions

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

    def load(self, path: Path, options: LoadOptions | None = None) -> Document:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AdapterError(f"cannot read {path.name!r}: {exc}") from exc

        text, encoding = _decode(raw)
        meta = {"encoding": encoding, "bytes": len(raw)}
        suffix = path.suffix.lower()
        if suffix in (".csv", ".tsv"):
            blocks = _table_blocks(text, "\t" if suffix == ".tsv" else None)
            if blocks is not None:
                meta["table"] = True
                return Document(path=path, kind="text", pages=[Page(index=0, blocks=blocks)], meta=meta)

        blocks = [
            Block(kind="text", text=line, source_ref={"line": number})
            for number, line in enumerate(text.splitlines())
        ]
        page = Page(index=0, blocks=blocks)
        return Document(path=path, kind="text", pages=[page], meta=meta)


def _table_blocks(text: str, delimiter: str | None) -> list[Block] | None:
    """Parse CSV/TSV into table rows, so changes are reported per cell.

    Returns ``None`` when the text does not parse as a table; it is then
    compared line by line like any other text file.
    """
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error:
        return None
    blocks: list[Block] = []
    for number, cells in enumerate(rows, start=1):
        while cells and not cells[-1].strip():
            cells.pop()
        if not cells:
            continue
        if len(cells) == 1:
            blocks.append(Block(kind="text", text=cells[0], label=str(number)))
            continue
        blocks.append(
            Block(
                kind="text",
                text=" | ".join(cells),
                cells=cells,
                label=str(number),
                source_ref={"line": number - 1},
            )
        )
    return blocks


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
