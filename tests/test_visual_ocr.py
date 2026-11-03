"""Visual (pixel) comparison, the image adapter and the OCR layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from diffanydoc.core import ocr, visual
from diffanydoc.core.adapters import LoadOptions, load
from diffanydoc.core.diff import DiffOptions, compare
from diffanydoc.core.render import render_page

from .pdfgen import write_pdf


@pytest.fixture(autouse=True)
def _isolated_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DIFFANYDOC_CACHE_DIR", str(tmp_path / "cache"))
    yield
    ocr.reset_engine()


def _page(text_lines: list[str], size=(800, 1000), stamp: bool = False) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(text_lines):
        draw.text((60, 80 + index * 40), line, fill="black")
    if stamp:
        draw.rectangle((500, 700, 700, 800), outline="black", width=4)
    return image


# --------------------------------------------------------------------------- #
# Pixel comparison
# --------------------------------------------------------------------------- #


def test_identical_renders_have_no_regions() -> None:
    page = _page(["Invoice 1", "Total 1000"])
    result, _ = visual.compare_images(page, page.copy(), page_size=page.size)
    assert result.identical and result.changed_ratio == 0


def test_shift_blur_and_jpeg_noise_are_tolerated(tmp_path: Path) -> None:
    page = _page(["Invoice 2024-001", "Customer: Acme", "Total: 1000 EUR"] * 5)
    moved = Image.new("RGB", page.size, "white")
    moved.paste(page, (6, -4))
    moved = moved.filter(ImageFilter.GaussianBlur(0.8))
    moved.save(tmp_path / "noisy.jpg", quality=50)
    result, _ = visual.compare_images(page, Image.open(tmp_path / "noisy.jpg"), page_size=page.size)
    assert result.regions == []
    assert result.offset == (-6.0, 4.0)


def test_added_stamp_is_found_where_it_is() -> None:
    before = _page(["Contract", "Signed by both parties"])
    after = _page(["Contract", "Signed by both parties"], stamp=True)
    result, diff = visual.compare_images(before, after, page_size=(400.0, 500.0))
    assert len(result.regions) == 1
    region = result.regions[0]
    assert region.kind == "insert"
    # Page units: the 800x1000 image maps onto a 400x500 page.
    assert 240 <= region.x0 <= 252 and 345 <= region.top <= 352
    assert 348 <= region.x1 <= 356 and 398 <= region.bottom <= 404
    overlay = visual.overlay_image(diff)
    assert overlay.size == (800, 1000)
    assert overlay.getpixel((600, 702))[1] > overlay.getpixel((600, 702))[0]  # green


def test_pdf_visual_diff_runs_on_request(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "l.pdf", [["Total: 1000 EUR"], ["Same page"]])
    right = write_pdf(tmp_path / "r.pdf", [["Total: 1250 EUR"], ["Same page"]])
    assert compare(left, right).visual is None  # text PDFs: off unless asked
    result = compare(left, right, DiffOptions(visual="on"))
    assert result.visual is not None and len(result.visual) == 2
    assert result.visual[0].regions and result.visual[1].identical
    assert result.stats.visual_regions == len(result.visual[0].regions)


def test_inserted_page_is_one_full_page_region(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "l.pdf", [["Cover page text"], ["Terms and conditions"]])
    right = write_pdf(
        tmp_path / "r.pdf", [["Cover page text"], ["Annex with new pricing"], ["Terms and conditions"]]
    )
    result = compare(left, right, DiffOptions(visual="on"))
    inserted = [p for p in result.visual if p.left is None]
    assert len(inserted) == 1 and inserted[0].regions[0].kind == "insert"


# --------------------------------------------------------------------------- #
# Image adapter
# --------------------------------------------------------------------------- #


def test_image_adapter_and_automatic_visual_diff(tmp_path: Path) -> None:
    ocr.set_engine(None)
    _page(["Plan A"]).save(tmp_path / "a.png")
    _page(["Plan A"], stamp=True).save(tmp_path / "b.png")
    document = load(tmp_path / "a.png")
    assert document.kind == "image" and document.renderable
    assert (document.pages[0].width, document.pages[0].height) == (800, 1000)
    assert any(w["code"] == "ocr_unavailable" for w in document.warnings)

    result = compare(tmp_path / "a.png", tmp_path / "b.png")
    assert result.visual is not None
    assert not result.identical  # no text, but the pixels differ
    assert result.stats.visual_regions == 1


def test_multiframe_tiff_is_multipage(tmp_path: Path) -> None:
    ocr.set_engine(None)
    frames = [_page(["one"]), _page(["two"])]
    frames[0].save(tmp_path / "scan.tiff", save_all=True, append_images=frames[1:])
    document = load(tmp_path / "scan.tiff")
    assert document.page_count == 2
    assert render_page(document, 1, 72).size == (800, 1000)


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #


class FakeEngine:
    """Deterministic engine: every page reads as the given lines."""

    name = "fake"

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.calls = 0

    def version(self) -> str:
        return "1"

    def languages(self) -> list[str]:
        return ["eng"]

    def default_language(self) -> str:
        return "eng"

    def recognize(self, image, lang):
        self.calls += 1
        words = []
        for row, line in enumerate(self.lines):
            x = 100
            for word in line.split():
                words.append(ocr.OcrWord(word, (x, 100 + row * 50, x + 20 * len(word), 130 + row * 50), 90.0, (1, 1, 1, row)))
                x += 20 * len(word) + 20
        return words


def _scanned_pdf(path: Path) -> Path:
    # A PDF page with no text layer: an image only.
    _page(["(pixels only)"]).save(path, resolution=100)
    return path


def test_scanned_pdf_pages_are_ocred_and_cached(tmp_path: Path) -> None:
    engine = FakeEngine(["Invoice 2024-001", "Total 1000 EUR"])
    ocr.set_engine(engine)
    path = _scanned_pdf(tmp_path / "scan.pdf")

    document = load(path)
    page = document.pages[0]
    assert page.source == "ocr"
    assert [b.text for b in page.blocks] == ["Invoice 2024-001", "Total 1000 EUR"]
    assert page.blocks[0].style["ocr"] is True
    # Pixel boxes were converted to page units (points).
    assert page.blocks[0].bbox[2] < page.width
    assert any(w["code"] == "ocr_used" for w in document.warnings)
    assert engine.calls == 1

    load(path)  # cache hit: the engine is not asked again
    assert engine.calls == 1
    load(path, LoadOptions(ocr_lang="tur"))  # other language: new cache key
    assert engine.calls == 2


def test_ocr_off_and_unavailable_are_reported(tmp_path: Path) -> None:
    path = _scanned_pdf(tmp_path / "scan.pdf")
    off = load(path, LoadOptions(ocr="off"))
    assert off.pages[0].source == "none"
    assert off.warnings[0]["code"] == "no_text_layer"

    ocr.set_engine(None)
    missing = load(path)
    assert missing.warnings[0]["code"] == "ocr_unavailable"


def test_ocr_force_reads_text_pdfs_too(tmp_path: Path) -> None:
    engine = FakeEngine(["from ocr"])
    ocr.set_engine(engine)
    path = write_pdf(tmp_path / "text.pdf", [["from the text layer"]])
    assert load(path).pages[0].blocks[0].text == "from the text layer"
    assert load(path, LoadOptions(ocr="force")).pages[0].blocks[0].text == "from ocr"


def test_scans_get_text_and_visual_comparison(tmp_path: Path) -> None:
    ocr.set_engine(FakeEngine(["Total 1000 EUR"]))
    left = _scanned_pdf(tmp_path / "l.pdf")
    _page(["(pixels only)"], stamp=True).save(tmp_path / "r.pdf", resolution=100)
    result = compare(left, tmp_path / "r.pdf")
    assert result.text_identical  # the fake engine reads the same text
    assert result.visual and result.visual[0].regions  # but the stamp is seen
    assert not result.identical


def test_parse_tsv() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t30\t12\t96.5\tHello\n"
        "5\t1\t1\t1\t1\t2\t45\t20\t30\t12\t12.0\tnoise\n"
        "4\t1\t1\t1\t1\t0\t10\t20\t70\t12\t-1\t\n"
    )
    words = ocr.parse_tsv(tsv)
    assert [w.text for w in words] == ["Hello"]
    assert words[0].bbox == (10, 20, 40, 32)


@pytest.mark.skipif(ocr.find_tesseract() is None, reason="tesseract is not installed")
def test_real_tesseract_reads_a_rendered_page(tmp_path: Path) -> None:
    ocr.reset_engine()
    pdf = write_pdf(tmp_path / "text.pdf", [["Invoice 2024-001", "Total: 1000 EUR"]])
    render_page(pdf, 0, 300).save(tmp_path / "scan.png")
    document = load(tmp_path / "scan.png")
    text = document.text(" ")
    assert "Invoice" in text and "1000" in text
