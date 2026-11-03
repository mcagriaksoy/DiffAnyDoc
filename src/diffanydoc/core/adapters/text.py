"""Plain-text adapter, also used as the fallback for unknown-but-textual files."""

from __future__ import annotations

import csv
import io
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
        suffix = path.suffix.lower()
        if suffix in (".csv", ".tsv"):
            blocks = _parse_delimited(text, delimiter="\t" if suffix == ".tsv" else None)
            kind = "csv"
        else:
            blocks = [
                Block(kind="text", text=line, source_ref={"line": number})
                for number, line in enumerate(text.splitlines())
            ]
            kind = "text"
        page = Page(index=0, blocks=blocks)
        return Document(
            path=path,
            kind=kind,
            pages=[page],
            meta={"encoding": encoding, "bytes": len(raw)},
        )


def _parse_delimited(text: str, *, delimiter: str | None = None) -> list[Block]:
    """Parse CSV/TSV into a structured table block so cells are aligned individually."""
    if not text.strip():
        return []
    sample = text[:4096]
    sep = delimiter
    if sep is None:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            sep = dialect.delimiter
        except csv.Error:
            sep = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.reader(io.StringIO(text), delimiter=sep)
    rows: list[Block] = []
    for row_idx, raw_row in enumerate(reader):
        if not raw_row or not any(cell.strip() for cell in raw_row):
            continue
        cells = [
            Block(
                kind="cell",
                text=cell.strip(),
                source_ref={"row": row_idx + 1, "col": col_idx + 1},
            )
            for col_idx, cell in enumerate(raw_row)
        ]
        rows.append(
            Block(
                kind="table_row",
                text=" | ".join(c.text for c in cells),
                children=cells,
                style={"row": row_idx + 1, "header": row_idx == 0},
                source_ref={"row": row_idx + 1},
            )
        )
    if not rows:
        return []
    return [
        Block(
            kind="table",
            text="\n".join(r.text for r in rows),
            children=rows,
            source_ref={"rows": len(rows)},
        )
    ]


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
