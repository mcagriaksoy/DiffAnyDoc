"""Visual (pixel) comparison tests."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from diffanydoc.core.adapters import load
from diffanydoc.core.diff import DiffOptions, compare
from diffanydoc.core.diff.align import align_pages
from diffanydoc.core.visual import (
    VisualOptions,
    _estimate_shift,
    _mask_regions,
    compare_pdf_pages,
)

from .pdfgen import write_pdf


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    left = write_pdf(
        tmp_path / "visual-left.pdf",
        [["Invoice 2024-001", "Customer: Acme", "Total: 1000 EUR"]],
    )
    right = write_pdf(
        tmp_path / "visual-right.pdf",
        [["Invoice 2024-001", "Customer: Acme", "Total: 1250 EUR"]],
    )
    return left, right


def test_identical_pdfs_have_no_visual_change(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "same.pdf", [["Invoice", "Total: 10 EUR"]])
    result = compare(path, path, DiffOptions(visual=True))

    assert result.visual is not None
    assert result.visual.compared == 1
    assert result.visual.changed_pages == 0
    assert result.visual.changed_pixels == 0
    assert result.visual.similarity == 1.0
    assert result.visual.region_count == 0


def test_visual_diff_reports_regions(tmp_path: Path) -> None:
    result = compare(*_pair(tmp_path), DiffOptions(visual=True))
    visual = result.visual

    assert visual is not None
    assert visual.compared == 1
    assert visual.changed_pages == 1
    assert 0 < visual.similarity < 1
    assert visual.changed_pixels > 0
    assert visual.region_count > 0

    page = visual.pages[0]
    assert page.left == 0 and page.right == 0
    assert page.left_regions and page.right_regions
    for box in page.left_regions + page.right_regions:
        x0, top, x1, bottom = box
        assert 0 <= x0 < x1 <= 595
        assert 0 <= top < bottom <= 842
        assert x1 - x0 >= 0.5 and bottom - top >= 0.5


def test_regions_cover_the_changed_text(tmp_path: Path) -> None:
    """The amount is on the third line; a box must land there."""
    result = compare(*_pair(tmp_path), DiffOptions(visual=True))
    assert result.visual is not None
    page = result.visual.pages[0]

    # The generator writes the first baseline 72 pt below the top edge and
    # steps 16 pt per line, so the amount sits around 104 pt from the top.
    boxes = page.left_regions
    assert any(80 <= box[1] <= 115 for box in boxes)
    assert all(box[1] < 120 for box in boxes)


def test_visual_is_opt_in(tmp_path: Path) -> None:
    left, right = _pair(tmp_path)
    assert compare(left, right).visual is None


def test_visual_skips_non_pdf_documents(tmp_path: Path) -> None:
    left = tmp_path / "a.txt"
    right = tmp_path / "b.txt"
    left.write_text("alpha\n", encoding="utf-8")
    right.write_text("beta\n", encoding="utf-8")

    assert compare(left, right, DiffOptions(visual=True)).visual is None


def test_tolerance_can_hide_changes(tmp_path: Path) -> None:
    result = compare(
        *_pair(tmp_path),
        DiffOptions(visual=True, visual_tolerance=255),
    )
    assert result.visual is not None
    assert result.visual.changed_pixels == 0
    assert result.visual.region_count == 0


def test_unpaired_pages_are_skipped(tmp_path: Path) -> None:
    left = write_pdf(
        tmp_path / "two.pdf",
        [["Invoice 2024-001"], ["Second page"]],
    )
    right = write_pdf(tmp_path / "one.pdf", [["Invoice 2024-001"]])

    result = compare(left, right, DiffOptions(visual=True))
    assert result.visual is not None
    assert result.visual.compared == 1
    assert all(page.left is not None and page.right is not None for page in result.visual.pages)


def test_max_pages_truncates(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "pages-l.pdf", [["one"], ["two"]])
    right = write_pdf(tmp_path / "pages-r.pdf", [["one"], ["two"]])

    result = compare(left, right, DiffOptions(visual=True, visual_max_pages=1))
    assert result.visual is not None
    assert result.visual.truncated is True
    assert result.visual.compared == 1


def test_registration_finds_a_small_shift() -> None:
    left = Image.new("L", (200, 200), 255)
    ImageDraw.Draw(left).rectangle((60, 70, 140, 130), fill=0)

    right = Image.new("L", (200, 200), 255)
    right.paste(left.crop((0, 0, 195, 195)), (4, 3))

    assert _estimate_shift(left, right, max_shift_px=6) == (-4, -3)


def test_blank_pages_are_not_registered() -> None:
    left = Image.new("L", (100, 100), 255)
    right = Image.new("L", (100, 100), 255)
    assert _estimate_shift(left, right, max_shift_px=4) == (0, 0)


def test_mask_regions_finds_rows_and_columns() -> None:
    mask = Image.new("L", (200, 120), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((20, 10, 60, 20), fill=255)
    draw.rectangle((20, 60, 150, 70), fill=255)

    boxes = _mask_regions(mask, scale=96 / 72)

    assert len(boxes) == 2
    tops = sorted(box[1] for box in boxes)
    assert tops == [9, 59]
    assert all(box[2] > box[0] for box in boxes)


def test_compare_pdf_pages_accepts_explicit_options(tmp_path: Path) -> None:
    left, right = _pair(tmp_path)
    page_map = align_pages(load(left), load(right))
    visual = compare_pdf_pages(
        left, right, page_map, VisualOptions(dpi=72, tolerance=10)
    )

    assert visual.compared == 1
    assert visual.pages[0].total_pixels > 0


def test_text_boxes_match_render_on_cropped_page(tmp_path: Path) -> None:
    from diffanydoc.core.render import render_page

    from .pdfgen import build_pdf

    raw = build_pdf([["HELLO WORLD", "SECOND LINE"]]).replace(
        b"/MediaBox [0 0 595 842]",
        b"/MediaBox [0 0 595 842] /CropBox [40 120 555 802]",
    )
    pdf = tmp_path / "cropped.pdf"
    pdf.write_bytes(raw)

    page = load(pdf).pages[0]
    assert (page.width, page.height) == (515.0, 682.0)

    scale = 2.0
    image = render_page(pdf, 0, 144).convert("L")
    x0, top, x1, bottom = page.blocks[0].bbox
    columns = range(int(x0 * scale), int(x1 * scale))
    ink = [
        y
        for y in range(int((top - 4) * scale), int((bottom + 4) * scale))
        if any(image.getpixel((x, y)) < 140 for x in columns)
    ]
    # Ink of the first line sits inside its box.
    assert ink
    assert top <= ink[0] / scale and ink[-1] / scale <= bottom
