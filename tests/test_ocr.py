from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from diffanydoc.core.diff import DiffOptions, compare
from diffanydoc.core.ocr import (
    OcrOptions,
    OcrUnavailable,
    _parse_tsv,
    apply_ocr,
    clear_cache,
)
from diffanydoc.core.adapters import load

from .pdfgen import write_pdf

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="fake Tesseract script uses a POSIX shebang"
)

_HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
    "left\ttop\twidth\theight\tconf\ttext"
)


def _fake_tesseract(tmp_path: Path) -> Path:
    """A Tesseract stand-in: one line of text that changes per invocation."""
    counter = tmp_path / "calls.txt"
    script = tmp_path / "fake-tesseract"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"counter = {str(counter)!r}\n"
        "try:\n"
        "    n = int(open(counter).read()) + 1\n"
        "except (OSError, ValueError):\n"
        "    n = 1\n"
        "open(counter, 'w').write(str(n))\n"
        "sys.stdin.buffer.read()\n"
        "print('level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\t"
        "left\\ttop\\twidth\\theight\\tconf\\ttext')\n"
        "print('5\\t1\\t1\\t1\\t1\\t1\\t100\\t100\\t120\\t30\\t95.5\\tTotal')\n"
        "print(f'5\\t1\\t1\\t1\\t1\\t2\\t240\\t100\\t90\\t30\\t94.0\\t{n * 100}')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _blank_pair(tmp_path: Path) -> tuple[Path, Path]:
    # Different page sizes give different content hashes, so the two scans
    # do not share a cache entry (identical files intentionally would).
    left = write_pdf(tmp_path / "left.pdf", [[]], width=595)
    right = write_pdf(tmp_path / "right.pdf", [[]], width=596)
    return left, right


def test_parse_tsv_groups_words_into_lines_with_points() -> None:
    tsv = "\n".join(
        [
            _HEADER,
            "5\t1\t1\t1\t1\t1\t100\t200\t80\t20\t90\tHello",
            "5\t1\t1\t1\t1\t2\t200\t200\t100\t20\t80\tworld",
            "5\t1\t1\t1\t2\t1\t100\t240\t60\t20\t70\tNext",
            "4\t1\t1\t1\t1\t0\t0\t0\t0\t0\t-1\t",
        ]
    )
    lines = _parse_tsv(tsv, dpi=200)  # 200 px/inch -> 0.36 pt/px
    assert [line["text"] for line in lines] == ["Hello world", "Next"]
    assert lines[0]["bbox"] == (36.0, 72.0, 108.0, 79.2)
    assert lines[0]["confidence"] == 85.0


def test_blank_pdf_page_is_ocred(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "scan.pdf", [[]])
    document = load(path)
    assert document.pages[0].blocks == []

    stats = apply_ocr(
        document,
        OcrOptions(binary=str(_fake_tesseract(tmp_path)), cache_dir=tmp_path / "cache"),
    )

    assert stats is not None and stats.pages == 1 and stats.cached == 0
    assert [block.text for block in document.pages[0].blocks] == ["Total 100"]
    assert document.pages[0].blocks[0].style["ocr"] is True
    assert document.pages[0].blocks[0].bbox is not None
    assert document.meta["ocr"]["pages"] == 1


def test_text_pdf_is_not_ocred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_pdf(tmp_path / "text.pdf", [["Already has a text layer"]])
    monkeypatch.setattr("diffanydoc.core.ocr.shutil.which", lambda _name: None)
    document = load(path)
    assert apply_ocr(document, OcrOptions(cache_dir=tmp_path)) is None
    assert document.meta.get("ocr") is None


def test_missing_tesseract_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    left, right = _blank_pair(tmp_path)
    monkeypatch.delenv("DIFFANYDOC_TESSERACT", raising=False)
    monkeypatch.setattr("diffanydoc.core.ocr.shutil.which", lambda _name: None)
    monkeypatch.setattr("diffanydoc.core.ocr._rapidocr_available", lambda: False)

    with pytest.raises(OcrUnavailable):
        compare(
            left,
            right,
            DiffOptions(ocr=True, ocr_cache_dir=str(tmp_path / "cache")),
        )


def test_ocr_changes_reach_the_diff_and_cache_reuses_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left, right = _blank_pair(tmp_path)
    fake = _fake_tesseract(tmp_path)
    cache = tmp_path / "cache"
    monkeypatch.setattr("diffanydoc.core.ocr._tesseract_binary", lambda _options: str(fake))

    options = DiffOptions(ocr=True, ocr_cache_dir=str(cache))
    first = compare(left, right, options)

    assert first.ocr is not None
    assert first.ocr.pages == 2 and first.ocr.cached == 0
    changed = [row for row in first.rows if row.kind == "replace"]
    assert len(changed) == 1
    assert changed[0].left and changed[0].left.text == "Total 100"
    assert changed[0].right and changed[0].right.text == "Total 200"

    second = compare(left, right, options)
    assert second.ocr is not None
    assert second.ocr.pages == 2 and second.ocr.cached == 2
    assert [(row.kind, row.left.text if row.left else None, row.right.text if row.right else None) for row in second.rows] == [
        (row.kind, row.left.text if row.left else None, row.right.text if row.right else None)
        for row in first.rows
    ]

    assert clear_cache(OcrOptions(cache_dir=cache)) >= 2


def test_ocr_can_be_limited_to_a_page_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_pdf(tmp_path / "many.pdf", [[], [], []])
    fake = _fake_tesseract(tmp_path)
    monkeypatch.setattr("diffanydoc.core.ocr._tesseract_binary", lambda _options: str(fake))

    document = load(path)
    stats = apply_ocr(
        document,
        OcrOptions(
            binary=str(fake),
            max_pages=2,
            cache_dir=tmp_path / "cache",
        ),
    )
    assert stats is not None
    assert stats.pages == 2 and stats.truncated is True
    assert document.pages[2].blocks == []


def test_cli_reports_ocr_and_uses_the_cache_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from diffanydoc.cli import main

    left, right = _blank_pair(tmp_path)
    fake = _fake_tesseract(tmp_path)
    monkeypatch.setattr("diffanydoc.core.ocr._tesseract_binary", lambda _options: str(fake))
    monkeypatch.setenv("DIFFANYDOC_CACHE_DIR", str(tmp_path / "cache"))

    assert main(["diff", str(left), str(right), "--ocr"]) == 0
    output = capsys.readouterr().out
    assert "ocr: 2 pages scanned (0 cached)" in output

    assert main(["diff", str(left), str(right), "--ocr"]) == 0
    assert "(2 cached)" in capsys.readouterr().out


def test_cli_explains_missing_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from diffanydoc.cli import main

    left, right = _blank_pair(tmp_path)
    monkeypatch.setenv("DIFFANYDOC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("DIFFANYDOC_TESSERACT", raising=False)
    monkeypatch.setattr("diffanydoc.core.ocr.shutil.which", lambda _name: None)
    monkeypatch.setattr("diffanydoc.core.ocr._rapidocr_available", lambda: False)

    assert main(["diff", str(left), str(right), "--ocr"]) == 2
    assert "tesseract is required" in capsys.readouterr().err


def test_rapidocr_embedded_engine_recognizes_image_without_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image, ImageDraw

    monkeypatch.delenv("DIFFANYDOC_TESSERACT", raising=False)
    monkeypatch.setattr("diffanydoc.core.ocr.shutil.which", lambda _name: None)

    left_img = tmp_path / "rapid_a.png"
    right_img = tmp_path / "rapid_b.png"

    im1 = Image.new("RGB", (320, 90), "white")
    ImageDraw.Draw(im1).text((20, 24), "INVOICE 1000 EUR", fill="black")
    im1.save(left_img)

    im2 = Image.new("RGB", (320, 90), "white")
    ImageDraw.Draw(im2).text((20, 24), "INVOICE 1250 EUR", fill="black")
    im2.save(right_img)

    result = compare(
        left_img,
        right_img,
        DiffOptions(ocr=True, visual=False, ocr_cache_dir=str(tmp_path / "cache")),
    )
    assert result.ocr is not None and result.ocr.pages == 2
    assert result.ocr.words >= 2
    assert any(row.kind == "replace" for row in result.rows)


def test_image_adapter_and_ocr_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image, ImageDraw

    left_img = tmp_path / "scan_a.png"
    right_img = tmp_path / "scan_b.png"

    im1 = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(im1).rectangle((20, 20, 120, 60), fill="black")
    im1.save(left_img)

    im2 = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(im2).rectangle((20, 100, 180, 150), fill="black")
    im2.save(right_img)

    fake = _fake_tesseract(tmp_path)
    monkeypatch.setattr("diffanydoc.core.ocr._tesseract_binary", lambda _options: str(fake))

    result = compare(
        left_img,
        right_img,
        DiffOptions(ocr=True, visual=True, ocr_cache_dir=str(tmp_path / "cache")),
    )
    assert result.left_kind == "image"
    assert result.right_kind == "image"
    assert result.ocr is not None and result.ocr.pages == 2
    assert result.visual is not None and result.visual.changed_pages == 1
    assert any(row.kind == "replace" for row in result.rows)


def test_doc_and_rtf_compared_against_pdf(tmp_path: Path) -> None:
    rtf_path = tmp_path / "contract.rtf"
    rtf_path.write_text(
        r"{\rtf1\ansi{\fonttbl\f0 Arial;}\pard Invoice 2024-001\par Customer: Acme\par Total: 1000 EUR\par}",
        encoding="utf-8",
    )
    doc_path = tmp_path / "contract.doc"
    doc_path.write_bytes(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        + b"\x00" * 64
        + "Invoice 2024-001\r\nCustomer: Acme\r\nTotal: 900 EUR\r\n".encode("utf-16le")
    )
    pdf_path = write_pdf(
        tmp_path / "contract.pdf",
        [["Invoice 2024-001", "Customer: Acme", "Total: 1250 EUR"]],
    )

    rtf_vs_pdf = compare(rtf_path, pdf_path)
    assert rtf_vs_pdf.left_kind == "doc"
    assert rtf_vs_pdf.right_kind == "pdf"
    assert rtf_vs_pdf.stats.changed == 1
    changed_rtf = [r for r in rtf_vs_pdf.rows if r.kind == "replace"]
    assert changed_rtf and "1000" in changed_rtf[0].left.text and "1250" in changed_rtf[0].right.text

    doc_vs_pdf = compare(doc_path, pdf_path)
    assert doc_vs_pdf.left_kind == "doc"
    assert doc_vs_pdf.right_kind == "pdf"
    changed_doc = [r for r in doc_vs_pdf.rows if r.kind == "replace"]
    assert changed_doc and "900" in changed_doc[0].left.text and "1250" in changed_doc[0].right.text

