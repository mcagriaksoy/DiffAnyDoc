"""Tests for email (.eml) and archive (.zip) adapter (TASK-24)."""

from __future__ import annotations

import zipfile
from email.message import EmailMessage
from pathlib import Path

from diffanydoc.core.adapters import load


def test_eml_adapter_extracts_headers_body_and_attachments(tmp_path: Path) -> None:
    eml = tmp_path / "sample.eml"
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bob@example.com"
    msg["Subject"] = "Contract v2"
    msg.set_content("Please review the attached contract.\nThanks, Alice.")
    msg.add_attachment(b"pdf-bytes", maintype="application", subtype="pdf", filename="contract.pdf")
    eml.write_bytes(msg.as_bytes())

    doc = load(eml)
    assert doc.kind == "eml"
    assert doc.page_count == 1
    texts = [b.text for b in doc.pages[0].blocks]
    assert "From: alice@example.com" in texts
    assert "Subject: Contract v2" in texts
    assert "Please review the attached contract." in texts
    assert "[Attachment] contract.pdf (9 B)" in texts


def test_zip_adapter_lists_entries_sorted(tmp_path: Path) -> None:
    zpath = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("b.txt", "hello")
        zf.writestr("a.txt", "world!")

    doc = load(zpath)
    assert doc.kind == "zip"
    assert doc.page_count == 1
    texts = [b.text for b in doc.pages[0].blocks]
    assert texts == ["a.txt (6 B)", "b.txt (5 B)"]
