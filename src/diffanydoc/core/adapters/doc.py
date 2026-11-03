"""Legacy and open word-processor adapter: .doc, .odt and .rtf files.

Allows comparing a ``.doc``, ``.odt`` or ``.rtf`` document directly against a
``.pdf`` or ``.docx`` through the shared :class:`~diffanydoc.core.model.Document` IR.

Extraction strategy (permissive-only, no third-party Python parser):
- ``.odt``: OpenDocument XML (``content.xml`` inside a ZIP archive).
- ``.rtf``: Built-in RTF control-word stripper and hex/Unicode decoder.
- ``.doc``: Headless LibreOffice/soffice conversion to ``.docx`` when available,
  or ``antiword`` / ``catdoc``, or a pure-Python OLE2/Word-stream text extractor
  so ``.doc`` files remain readable even without external tools.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..model import Block, Document, Page
from .base import AdapterError
from .docx import DocxAdapter

_DOC_EXTENSIONS = (".doc", ".odt", ".rtf")

_ODT_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_ODT_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"


class DocAdapter:
    name = "doc"
    extensions = _DOC_EXTENSIONS

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def load(self, path: Path) -> Document:
        suffix = path.suffix.lower()
        try:
            if suffix == ".odt":
                return _load_odt(path)
            if suffix == ".rtf":
                return _load_rtf(path)
            return _load_doc(path)
        except AdapterError:
            raise
        except OSError as exc:
            raise AdapterError(f"cannot read {path.name!r}: {exc}") from exc


# --------------------------------------------------------------------------- #
# ODT (OpenDocument Text)
# --------------------------------------------------------------------------- #


def _load_odt(path: Path) -> Document:
    try:
        with zipfile.ZipFile(path) as package:
            try:
                content_xml = package.read("content.xml")
            except KeyError as exc:
                raise AdapterError(
                    f"{path.name!r} is not an ODT document (no content.xml)"
                ) from exc
    except zipfile.BadZipFile as exc:
        raise AdapterError(f"cannot read ODT {path.name!r}: {exc}") from exc

    try:
        root = ElementTree.fromstring(content_xml)
    except ElementTree.ParseError as exc:
        raise AdapterError(f"cannot parse ODT {path.name!r}: {exc}") from exc

    blocks: list[Block] = []
    table_index = 0
    for elem in root.iter():
        if elem.tag in (_ODT_TEXT + "p", _ODT_TEXT + "h"):
            text = "".join(elem.itertext()).strip()
            if text:
                blocks.append(
                    Block(
                        kind="text",
                        text=text,
                        style={"heading": elem.tag.endswith("h")},
                        source_ref={"line": len(blocks)},
                    )
                )
        elif elem.tag == _ODT_TABLE + "table":
            rows: list[Block] = []
            for r_idx, row in enumerate(elem.findall(_ODT_TABLE + "table-row")):
                cells: list[Block] = []
                for c_idx, cell in enumerate(row.findall(_ODT_TABLE + "table-cell")):
                    cell_text = " ".join(
                        part.strip()
                        for part in "".join(cell.itertext()).splitlines()
                        if part.strip()
                    )
                    cells.append(
                        Block(
                            kind="cell",
                            text=cell_text,
                            source_ref={
                                "table": table_index,
                                "row": r_idx,
                                "col": c_idx,
                            },
                        )
                    )
                if any(c.text for c in cells):
                    rows.append(
                        Block(
                            kind="table_row",
                            text=" | ".join(c.text for c in cells),
                            children=cells,
                            source_ref={"table": table_index, "row": r_idx},
                        )
                    )
            if rows:
                blocks.append(
                    Block(
                        kind="table",
                        text="\n".join(r.text for r in rows),
                        children=rows,
                        source_ref={"table": table_index, "rows": len(rows)},
                    )
                )
                table_index += 1

    return Document(
        path=path,
        kind="doc",
        pages=[Page(index=0, blocks=blocks)],
        meta={"format": "odt", "blocks": len(blocks)},
    )


# --------------------------------------------------------------------------- #
# RTF (Rich Text Format)
# --------------------------------------------------------------------------- #

_RTF_HEX = re.compile(r"\\'([0-9a-fA-F]{2})")
_RTF_UNICODE = re.compile(r"\\u(-?\d+)\??")
_RTF_SKIP_GROUPS = re.compile(
    r"\{\\(?:fonttbl|colortbl|stylesheet|info|pict|object|header|footer|\*\\[a-zA-Z]+)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
)
_RTF_BREAK = re.compile(r"\\(?:par|pard|line|row)\b\s?")
_RTF_CELL = re.compile(r"\\cell\b\s?")
_RTF_TAB = re.compile(r"\\tab\b\s?")
_RTF_CMD = re.compile(r"\\[a-zA-Z]+(?:-?\d+)?\s?")


def _load_rtf(path: Path) -> Document:
    raw = path.read_bytes()
    text = raw.decode("cp1252", errors="replace")
    if not text.lstrip().startswith("{\\rtf"):
        # Plain text saved with .rtf extension
        lines = [line.strip() for line in text.splitlines() if line.strip()]
    else:
        cleaned = _RTF_SKIP_GROUPS.sub("", text)
        cleaned = _RTF_HEX.sub(
            lambda m: bytes.fromhex(m.group(1)).decode("cp1254", errors="replace"),
            cleaned,
        )
        cleaned = _RTF_UNICODE.sub(
            lambda m: chr(int(m.group(1)) & 0xFFFF),
            cleaned,
        )
        cleaned = _RTF_BREAK.sub("\n", cleaned)
        cleaned = _RTF_CELL.sub(" | ", cleaned)
        cleaned = _RTF_TAB.sub("\t", cleaned)
        cleaned = (
            cleaned.replace(r"\{", "\x00")
            .replace(r"\}", "\x01")
            .replace(r"\\", "\x02")
        )
        cleaned = _RTF_CMD.sub("", cleaned)
        cleaned = cleaned.replace("{", "").replace("}", "")
        cleaned = (
            cleaned.replace("\x00", "{")
            .replace("\x01", "}")
            .replace("\x02", "\\")
        )
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    blocks = [
        Block(kind="text", text=line, source_ref={"line": idx})
        for idx, line in enumerate(lines)
    ]
    return Document(
        path=path,
        kind="doc",
        pages=[Page(index=0, blocks=blocks)],
        meta={"format": "rtf", "lines": len(blocks)},
    )


# --------------------------------------------------------------------------- #
# Legacy .DOC (Word 97-2004 / RTF-in-DOC / DOCX-in-DOC)
# --------------------------------------------------------------------------- #


def _load_doc(path: Path) -> Document:
    raw = path.read_bytes()
    if not raw:
        return Document(path=path, kind="doc", pages=[Page(index=0)], meta={"format": "doc"})

    # Case 1: A ZIP/DOCX saved with a .doc extension
    if raw[:4] == b"PK\x03\x04":
        doc = DocxAdapter().load(path)
        doc.kind = "doc"
        return doc

    # Case 2: An RTF saved with a .doc extension
    if raw.lstrip()[:5] == b"{\\rtf":
        return _load_rtf(path)

    # Case 3: Convert via LibreOffice / soffice to .docx if available and enabled
    converted = _convert_with_soffice(path)
    if converted is not None:
        return converted

    # Case 4: Convert via catdoc / antiword CLI if available
    cli_text = _extract_with_cli(path)
    if cli_text is not None:
        return _blocks_document(path, cli_text, extractor="cli")

    # Case 5: Built-in binary Word / OLE2 stream text extraction
    extracted = _extract_binary_doc_text(raw)
    if not extracted:
        raise AdapterError(f"cannot extract text from {path.name!r}")
    return _blocks_document(path, extracted, extractor="builtin")


def _convert_with_soffice(path: Path) -> Document | None:
    if shutil.which("soffice") is None and shutil.which("libreoffice") is None:
        return None
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        return None
    # Only invoke soffice on genuine OLE2 Compound Documents (D0 CF 11 E0)
    try:
        header = path.read_bytes()[:8]
    except OSError:
        return None
    if not header.startswith(b"\xd0\xcf\x11\xe0"):
        return None

    with tempfile.TemporaryDirectory(prefix="diffanydoc-doc-") as tmpdir:
        try:
            completed = subprocess.run(
                [
                    binary,
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    tmpdir,
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        candidates = list(Path(tmpdir).glob("*.docx"))
        if not candidates:
            return None
        try:
            doc = DocxAdapter().load(candidates[0])
        except AdapterError:
            return None
        doc.path = path
        doc.kind = "doc"
        doc.meta["extractor"] = "soffice"
        return doc


def _extract_with_cli(path: Path) -> list[str] | None:
    try:
        header = path.read_bytes()[:8]
    except OSError:
        return None
    if not header.startswith(b"\xd0\xcf\x11\xe0"):
        return None

    for tool, args in (("antiword", ["-w", "0"]), ("catdoc", ["-w"])):
        binary = shutil.which(tool)
        if not binary:
            continue
        try:
            completed = subprocess.run(
                [binary, *args, str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0 and completed.stdout.strip():
            text = completed.stdout.decode("utf-8", errors="replace")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                return lines
    return None


_ASCII_RUN = re.compile(rb"[\t\n\r\x20-\x7e\xa0-\xff]{4,}")
_UTF16_RUN = re.compile(rb"(?:[\t\n\r\x20-\x7e\xa0-\xff]\x00|[\x00-\xff][\x01-\x04]){4,}")
_NOISE_MARKERS = {
    "Root Entry",
    "WordDocument",
    "SummaryInformation",
    "DocumentSummaryInformation",
    "CompObj",
    "1Table",
    "0Table",
    "Normal.dotm",
    "Normal.dot",
    "Times New Roman",
    "Calibri",
    "Arial",
    "MSWordDoc",
    "Word.Document.8",
}


def _extract_binary_doc_text(raw: bytes) -> list[str]:
    """Extract readable lines from an OLE2 .doc or plain text buffer."""
    # If the file is mostly plain UTF-8 / CP1254 text (e.g. a text file named .doc)
    if not raw.startswith(b"\xd0\xcf\x11\xe0"):
        for encoding in ("utf-8-sig", "utf-16", "cp1254", "cp1252", "latin-1"):
            try:
                decoded = raw.decode(encoding)
                return [line.strip() for line in decoded.splitlines() if line.strip()]
            except UnicodeDecodeError:
                continue

    chunks: list[str] = []
    # Extract UTF-16LE runs (Word 97+ stores Unicode pieces in UTF-16LE)
    for match in _UTF16_RUN.finditer(raw):
        piece = match.group(0)
        if len(piece) % 2:
            piece = piece[:-1]
        try:
            text = piece.decode("utf-16le", errors="ignore")
        except Exception:
            continue
        chunks.append(text)

    # Also extract 8-bit CP1254/CP1252 runs
    for match in _ASCII_RUN.finditer(raw):
        try:
            text = match.group(0).decode("cp1254", errors="ignore")
        except Exception:
            continue
        chunks.append(text)

    lines: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for raw_line in re.split(r"[\r\n\x07\x0b\x0c]+", chunk):
            cleaned = "".join(
                ch for ch in raw_line if ch.isprintable() or ch == "\t"
            ).strip()
            if len(cleaned) < 2 or cleaned in _NOISE_MARKERS:
                continue
            if not any(ch.isalpha() or ch.isdigit() for ch in cleaned):
                continue
            if cleaned not in seen:
                seen.add(cleaned)
                lines.append(cleaned)
    return lines


def _blocks_document(path: Path, lines: list[str], *, extractor: str) -> Document:
    blocks = [
        Block(kind="text", text=line, source_ref={"line": idx})
        for idx, line in enumerate(lines)
        if line
    ]
    return Document(
        path=path,
        kind="doc",
        pages=[Page(index=0, blocks=blocks)],
        meta={"format": "doc", "extractor": extractor, "lines": len(blocks)},
    )
