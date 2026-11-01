"""Visual (pixel) comparison of rendered PDF pages.

Text diffing misses everything that is not text: images, stamps, signature
blocks, vector charts, font changes that keep the same characters. The visual
layer renders both pages, compensates a small registration offset (scans and
printer margins rarely line up to the pixel), and reports changed regions in
PDF points so the viewer can draw them over the page image.

Only Pillow is used for the pixel work; pdfium renders the pages (see
``core.render``). Both are permissively licensed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat

from .model import BBox, PagePair, VisualDiff, VisualPage
from .render import render_page


@dataclass(slots=True)
class VisualOptions:
    """Tuning knobs for the pixel comparison."""

    #: Rendering resolution. 96 dpi keeps a page around 0.9 Mpx.
    dpi: int = 96
    #: Per-channel difference (0-255) below which two pixels count as equal.
    #: 24 hides JPEG/scan noise and anti-aliasing without hiding real edits.
    tolerance: int = 24
    #: Largest registration offset searched, in points.
    max_shift_pt: float = 4.0
    #: Safety valve for very long documents; the rest is reported as truncated.
    max_pages: int = 60


def compare_pdf_pages(
    left_path: str | Path,
    right_path: str | Path,
    page_map: list[PagePair],
    options: VisualOptions | None = None,
) -> VisualDiff:
    """Compare every aligned page pair pixel by pixel.

    Unpaired pages are skipped: the viewer already shows them as missing, and
    comparing a page against nothing would only produce one huge region.
    """
    options = options or VisualOptions()
    pairs = [pair for pair in page_map if pair.left is not None and pair.right is not None]
    truncated = len(pairs) > max(options.max_pages, 0)
    pairs = pairs[: max(options.max_pages, 0)]

    pages: list[VisualPage] = []
    for pair in pairs:
        try:
            pages.append(
                _compare_page(
                    left_path,
                    int(pair.left),
                    right_path,
                    int(pair.right),
                    options,
                )
            )
        except Exception as exc:  # a broken page must not fail the text diff
            pages.append(
                VisualPage(
                    left=int(pair.left),
                    right=int(pair.right),
                    error=str(exc),
                )
            )

    compared = [page for page in pages if page.total_pixels]
    changed = [page for page in compared if page.changed_pixels]
    return VisualDiff(
        pages=pages,
        compared=len(compared),
        changed_pages=len(changed),
        changed_pixels=sum(page.changed_pixels for page in compared),
        total_pixels=sum(page.total_pixels for page in compared),
        max_shift=max(
            (abs(page.shift[0]) + abs(page.shift[1]) for page in pages),
            default=0.0,
        ),
        truncated=truncated,
    )


# --------------------------------------------------------------------------- #
# One page pair
# --------------------------------------------------------------------------- #


def _compare_page(
    left_path: str | Path,
    left_index: int,
    right_path: str | Path,
    right_index: int,
    options: VisualOptions,
) -> VisualPage:
    scale = max(options.dpi, 24) / 72.0
    left = render_page(left_path, left_index, options.dpi)
    right = render_page(right_path, right_index, options.dpi)

    width = max(left.width, right.width)
    height = max(left.height, right.height)
    left_canvas = _canvas(left, width, height)
    right_canvas = _canvas(right, width, height)

    shift = _estimate_shift(
        left_canvas.convert("L"),
        right_canvas.convert("L"),
        max_shift_px=max(options.max_shift_pt, 0.0) * scale,
    )
    right_shifted = _canvas(right, width, height, dx=shift[0], dy=shift[1])

    diff = _difference(left_canvas, right_shifted)
    mask = diff.point(lambda value: 255 if value > options.tolerance else 0)

    # Median removes isolated scan specks; Max closes one-pixel gaps so a
    # dashed or anti-aliased glyph becomes one readable box instead of many.
    mask = mask.filter(ImageFilter.MedianFilter(3))
    mask = mask.filter(ImageFilter.MaxFilter(3))

    total_pixels = width * height
    changed_pixels = mask.histogram()[255]
    if changed_pixels / total_pixels < 0.00001:
        changed_pixels = 0
        mask = Image.new("L", (width, height), 0)

    boxes = _mask_regions(mask, scale)
    left_regions: list[BBox] = []
    right_regions: list[BBox] = []
    left_w, left_h = left.width / scale, left.height / scale
    right_w, right_h = right.width / scale, right.height / scale
    for box in boxes:
        left_box = _clip_to_page(box, scale, 0, 0, left_w, left_h)
        if left_box is not None:
            left_regions.append(left_box)
        right_box = _clip_to_page(
            box, scale, shift[0], shift[1], right_w, right_h
        )
        if right_box is not None:
            right_regions.append(right_box)

    return VisualPage(
        left=left_index,
        right=right_index,
        shift=(shift[0] / scale, shift[1] / scale),
        changed_pixels=changed_pixels,
        total_pixels=total_pixels,
        left_regions=left_regions,
        right_regions=right_regions,
    )


def _canvas(
    image: Image.Image, width: int, height: int, dx: int = 0, dy: int = 0
) -> Image.Image:
    """White canvas of the given size with the image pasted at an offset."""
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(image, (dx, dy))
    return canvas


def _difference(left: Image.Image, right: Image.Image) -> Image.Image:
    """Per-pixel maximum channel difference, as an 8-bit grey image."""
    diff = ImageChops.difference(left, right)
    red, green, blue = diff.split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def _estimate_shift(
    left: Image.Image, right: Image.Image, max_shift_px: float
) -> tuple[int, int]:
    """Find the (dx, dy) that best aligns ``right`` onto ``left``.

    Search is done on greyscale images over the overlapping part only, so the
    white padding introduced by a page-size difference does not win. A shift is
    accepted only if it clearly beats "no shift"; otherwise a clean pair of
    pages stays unregistered.
    """
    radius = int(round(max_shift_px))
    if radius <= 0:
        return (0, 0)

    base = _overlap_score(left, right, 0, 0)
    if base < 0.5:  # already identical within rounding: no need to search
        return (0, 0)
    if min(ImageStat.Stat(left).mean[0], ImageStat.Stat(right).mean[0]) > 250.0:
        return (0, 0)  # blank page, registration is meaningless

    best = (0, 0)
    best_score = base
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            score = _overlap_score(left, right, dx, dy)
            if score < best_score - 0.02:
                best_score = score
                best = (dx, dy)

    if best_score > base - 0.05:
        return (0, 0)
    return best


def _overlap_score(left: Image.Image, right: Image.Image, dx: int, dy: int) -> float:
    x0 = max(0, dx)
    y0 = max(0, dy)
    x1 = min(left.width, right.width + dx)
    y1 = min(left.height, right.height + dy)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 255.0
    a = left.crop((x0, y0, x1, y1))
    b = right.crop((x0 - dx, y0 - dy, x1 - dx, y1 - dy))
    return float(ImageStat.Stat(ImageChops.difference(a, b)).mean[0])


# --------------------------------------------------------------------------- #
# Region extraction
# --------------------------------------------------------------------------- #


def _column_projection(image: Image.Image) -> list[int] | tuple[int, ...]:
    """Per-column sums, working with both Pillow projection return shapes.

    Pillow 13 returns ``(columns, rows)`` from ``getprojection()``; earlier
    versions return the column sums alone.
    """
    projection = image.getprojection()
    return projection[0] if isinstance(projection, tuple) else projection


def _row_projection(image: Image.Image) -> list[int] | tuple[int, ...]:
    """Per-row sums, for both Pillow projection return shapes."""
    projection = image.getprojection()
    if isinstance(projection, tuple):
        return projection[1]
    return image.transpose(Image.Transpose.TRANSPOSE).getprojection()


def _runs(values: list[int] | tuple[int, ...], gap: int) -> list[tuple[int, int]]:
    """Group indexes with a non-zero value, tolerating short empty gaps."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    last = 0
    for index, value in enumerate(values):
        if value:
            if start is None:
                start = index
            last = index
        elif start is not None and index - last > gap:
            runs.append((start, last + 1))
            start = None
    if start is not None:
        runs.append((start, last + 1))
    return runs


def _mask_regions(mask: Image.Image, scale: float) -> list[BBox]:
    """Turn a change mask into boxes in canvas pixels.

    Rows first: changed text lines are separate bands. Inside each band the
    columns are grouped too, so a change in the right column does not paint the
    whole page width.
    """
    width, height = mask.size
    rows = _runs(_row_projection(mask), gap=max(1, round(scale * 2)))
    column_gap = max(2, round(scale * 8))
    boxes: list[BBox] = []
    for top, bottom in rows:
        band = mask.crop((0, top, width, bottom))
        band_height = bottom - top
        band_boxes: list[BBox] = []
        for x0, x1 in _runs(_column_projection(band), gap=column_gap):
            pixels = band.crop((x0, 0, x1, band_height)).histogram()[255]
            if pixels < 6:
                continue
            band_boxes.append(
                (
                    max(0, x0 - 1),
                    max(0, top - 1),
                    min(width, x1 + 1),
                    min(height, bottom + 1),
                )
            )
        if band_boxes and len(boxes) + len(band_boxes) > 120:
            # A dense page turns into hundreds of boxes that add nothing for
            # the reader; one box per changed line is the useful fallback.
            band_boxes = [
                (
                    min((box[0] for box in band_boxes), default=0),
                    max(0, top - 1),
                    max((box[2] for box in band_boxes), default=0),
                    min(height, bottom + 1),
                )
            ]
        boxes.extend(band_boxes)
    return boxes


def _clip_to_page(
    box: BBox,
    scale: float,
    dx: int,
    dy: int,
    page_width: float,
    page_height: float,
) -> BBox | None:
    x0 = (box[0] - dx) / scale
    top = (box[1] - dy) / scale
    x1 = (box[2] - dx) / scale
    bottom = (box[3] - dy) / scale
    x0 = max(0.0, min(page_width, x0))
    x1 = max(0.0, min(page_width, x1))
    top = max(0.0, min(page_height, top))
    bottom = max(0.0, min(page_height, bottom))
    if x1 - x0 < 0.5 or bottom - top < 0.5:
        return None
    return (x0, top, x1, bottom)


__all__ = ["VisualOptions", "compare_pdf_pages"]
