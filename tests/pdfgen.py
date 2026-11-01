"""Tiny dependency-free PDF writer used by tests.

Keeping test fixtures as generated PDFs means no binary blobs in the repo and
no extra dependency (reportlab) in the dev set.
"""

from __future__ import annotations

from pathlib import Path


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str], first_baseline: float, leading: float) -> str:
    parts = ["BT", "/F1 12 Tf", f"{leading} TL", f"72 {first_baseline} Td"]
    for index, line in enumerate(lines):
        if index:
            parts.append("T*")
        parts.append(f"({_escape(line)}) Tj")
    parts.append("ET")
    return "\n".join(parts) + "\n"


def build_pdf(pages: list[list[str]], width: float = 595, height: float = 842) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add(b"")  # placeholder, filled after page ids are known
    pages_id = add(b"")
    font_id = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )

    kids: list[str] = []
    for lines in pages:
        stream = _content_stream(lines, first_baseline=height - 72, leading=16).encode(
            "cp1252", errors="replace"
        )
        content_id = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream"
        )
        page_id = add(
            b"<< /Type /Page /Parent "
            + str(pages_id).encode()
            + b" 0 R /MediaBox [0 0 "
            + f"{width:.0f} {height:.0f}".encode()
            + b"] /Resources << /Font << /F1 "
            + str(font_id).encode()
            + b" 0 R >> >> /Contents "
            + str(content_id).encode()
            + b" 0 R >>"
        )
        kids.append(f"{page_id} 0 R")

    objects[catalog_id - 1] = (
        b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>"
    )
    objects[pages_id - 1] = (
        b"<< /Type /Pages /Count "
        + str(len(pages)).encode()
        + b" /Kids ["
        + " ".join(kids).encode()
        + b"] >>"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_at).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def write_pdf(path: Path, pages: list[list[str]]) -> Path:
    path.write_bytes(build_pdf(pages))
    return path
