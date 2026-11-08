"""Tests for PDF & HTML report generators."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pypdfium2
import pytest
from fastapi.testclient import TestClient

from diffanydoc.core.diff import DiffOptions, compare
from diffanydoc.core.report.pdf import render_pdf, write_pdf_report
from diffanydoc.web.server import create_app


def test_render_pdf_identical_files(tmp_path: Path) -> None:
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("Satır bir\nSatır iki\nSatır üç\n", encoding="utf-8")
    f2.write_text("Satır bir\nSatır iki\nSatır üç\n", encoding="utf-8")

    result = compare(f1, f2, DiffOptions())
    pdf_bytes = render_pdf(result, language="tr")

    assert pdf_bytes.startswith(b"%PDF-")
    doc = pypdfium2.PdfDocument(pdf_bytes)
    assert len(doc) >= 1


def test_render_pdf_with_changes(tmp_path: Path) -> None:
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("Giriş bölümü\nSilinecek metin\nDeğişecek metin sol\nSabit metin\n", encoding="utf-8")
    f2.write_text("Giriş bölümü\nDeğişecek metin sağ\nEklenen metin\nSabit metin\n", encoding="utf-8")

    result = compare(f1, f2, DiffOptions())
    pdf_bytes = render_pdf(result, language="en")

    assert pdf_bytes.startswith(b"%PDF-")
    doc = pypdfium2.PdfDocument(pdf_bytes)
    assert len(doc) >= 1


def test_render_pdf_multipage_pagination(tmp_path: Path) -> None:
    f1 = tmp_path / "long_a.txt"
    f2 = tmp_path / "long_b.txt"

    lines_a = [f"Clause paragraph line {i}: standard condition for testing" for i in range(120)]
    lines_b = [f"Clause paragraph line {i}: modified condition for testing" if i % 3 == 0 else f"Clause paragraph line {i}: standard condition for testing" for i in range(120)]

    f1.write_text("\n\n".join(lines_a), encoding="utf-8")
    f2.write_text("\n\n".join(lines_b), encoding="utf-8")

    result = compare(f1, f2, DiffOptions())
    pdf_bytes = render_pdf(result, language="en", max_pages=10)

    assert pdf_bytes.startswith(b"%PDF-")
    doc = pypdfium2.PdfDocument(pdf_bytes)
    assert len(doc) > 1, "Long comparison should paginate across multiple pages"


def test_write_pdf_report(tmp_path: Path) -> None:
    f1 = tmp_path / "left.txt"
    f2 = tmp_path / "right.txt"
    f1.write_text("Alpha\nBeta\n", encoding="utf-8")
    f2.write_text("Alpha\nGamma\n", encoding="utf-8")

    result = compare(f1, f2, DiffOptions())
    out_pdf = tmp_path / "output_report.pdf"
    ret = write_pdf_report(result, out_pdf, language="en")

    assert ret == out_pdf
    assert out_pdf.is_file()
    assert out_pdf.stat().st_size > 1000
    assert out_pdf.read_bytes().startswith(b"%PDF-")


def test_web_api_pdf_report_endpoint(tmp_path: Path) -> None:
    f1 = tmp_path / "api_l.txt"
    f2 = tmp_path / "api_r.txt"
    f1.write_text("Item 1: 100 USD\n", encoding="utf-8")
    f2.write_text("Item 1: 150 USD\n", encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    res = client.post(
        "/api/compare-paths",
        json={"left": str(f1), "right": str(f2)},
    )
    assert res.status_code == 200
    comp_id = res.json()["id"]

    pdf_res = client.get(f"/api/compare/{comp_id}/report.pdf?lang=en")
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert "diffanydoc-report-" in pdf_res.headers.get("content-disposition", "")
    assert pdf_res.content.startswith(b"%PDF-")


def test_cli_generates_pdf_report(tmp_path: Path) -> None:
    f1 = tmp_path / "cli_a.txt"
    f2 = tmp_path / "cli_b.txt"
    f1.write_text("CLI original text\n", encoding="utf-8")
    f2.write_text("CLI modified text\n", encoding="utf-8")

    out_pdf = tmp_path / "cli_report.pdf"

    cmd = [
        sys.executable,
        "-m",
        "diffanydoc.cli",
        "diff",
        str(f1),
        str(f2),
        "-o",
        str(out_pdf),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0
    assert out_pdf.is_file()
    assert out_pdf.read_bytes().startswith(b"%PDF-")
