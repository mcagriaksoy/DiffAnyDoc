"""Pure-stdlib adapter for email (.eml, .msg) and archive (.zip) files."""

from __future__ import annotations

import email
import email.policy
import re
import zipfile
from html import unescape
from pathlib import Path

from ..model import Block, Document, Page

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw)
    return re.sub(r"[ \t]+", " ", unescape(text)).strip()


def _load_eml(path: Path) -> list[Page]:
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    blocks: list[Block] = []
    for hdr in ("From", "To", "Cc", "Date", "Subject"):
        val = msg.get(hdr)
        if val:
            blocks.append(Block(text=f"{hdr}: {val}"))

    body_text = ""
    attachments: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            disp = part.get_content_disposition()
            fname = part.get_filename()
            if disp == "attachment" or fname:
                payload = part.get_payload(decode=True) or b""
                attachments.append(f"[Attachment] {fname or 'unnamed'} ({len(payload)} B)")
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and not body_text:
                body_text = part.get_content() or ""
            elif ctype == "text/html" and not body_text:
                body_text = _strip_html(str(part.get_content() or ""))
    else:
        ctype = msg.get_content_type()
        content = str(msg.get_content() or "")
        body_text = _strip_html(content) if ctype == "text/html" else content

    for line in body_text.splitlines():
        stripped = line.strip()
        if stripped:
            blocks.append(Block(text=stripped))
    for att in attachments:
        blocks.append(Block(text=att, kind="footnote"))
    return [Page(index=0, label="Email", blocks=blocks)]


def _load_msg(path: Path) -> list[Page]:
    """Best-effort pure-stdlib text extraction from OLE2 .msg files."""
    raw = path.read_bytes()
    # Extract UTF-16LE runs (common for Outlook .msg properties)
    runs = re.findall(rb"(?:[\x20-\x7e\u00a0-\u00ff]\x00){4,}", raw)
    blocks: list[Block] = []
    seen: set[str] = set()
    for run in runs:
        try:
            text = run.decode("utf-16-le", errors="ignore").strip()
        except Exception:
            continue
        if len(text) >= 4 and text not in seen:
            seen.add(text)
            blocks.append(Block(text=text))
    return [Page(index=0, label="Email", blocks=blocks)]


def _load_zip(path: Path) -> list[Page]:
    blocks: list[Block] = []
    with zipfile.ZipFile(path, "r") as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            if info.is_dir():
                continue
            blocks.append(Block(text=f"{info.filename} ({info.file_size} B)"))
    return [Page(index=0, label="Archive", blocks=blocks)]


class EmailArchiveAdapter:
    """Adapter for .eml, .msg, and .zip files."""

    name = "Email & Archive"
    extensions = (".eml", ".msg", ".zip")

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def load(self, path: Path) -> Document:
        ext = path.suffix.lower()
        if ext == ".eml":
            pages = _load_eml(path)
        elif ext == ".msg":
            pages = _load_msg(path)
        else:
            pages = _load_zip(path)
        return Document(path=path, kind=ext.lstrip("."), pages=pages)
