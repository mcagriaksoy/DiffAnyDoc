"""Visual (pixel) comparison of rendered pages.

The text diff cannot see a moved logo, a changed signature, a stamp, a chart,
a scanned page or a font substitution. This module renders both pages,
registers them (corrects a small shift, and scales when page sizes differ),
and compares them with a tolerance that ignores anti-aliasing:

* a pixel counts as *removed* when the left page is darker than the darkest
  pixel in the right page's neighbourhood by more than ``tolerance``, and as
  *added* the other way round — one-pixel rendering jitter therefore never
  counts;
* changed pixels are pooled into a coarse grid, connected into regions and
  reported in page units, so they overlay the page like the text boxes do.

Pillow only (no numpy/OpenCV), so the dependency set stays small and
permissively licensed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .model import Document, PagePair, VisualPage, VisualRegion

#: Rendering resolution for the comparison (pixels per inch of page).
DEFAULT_DPI = 100
#: Grey-level difference (0-255) below which pixels are equal.
DEFAULT_TOLERANCE = 40
#: Largest registration shift searched, as a share of the page size.
MAX_SHIFT = 0.03
#: Grid cell for pooling changed pixels into regions (pixels).
CELL = 6
#: Regions with fewer changed pixels than this are speckle.
MIN_PIXELS = 6


@dataclass(slots=True)
class VisualOptions:
    dpi: int = DEFAULT_DPI
    tolerance: int = DEFAULT_TOLERANCE
    register: bool = True


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def _pixels(image: Any) -> Any:
    # Pillow 12 renamed getdata(); support both.
    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter is not None else image.getdata()


def _profile(image: Any, axis: str) -> list[float]:
    """Mean darkness per row ("y") or per column ("x")."""
    from PIL import Image, ImageOps

    inverted = ImageOps.invert(image)
    if axis == "y":
        reduced = inverted.resize((1, inverted.height), Image.BOX)
    else:
        reduced = inverted.resize((inverted.width, 1), Image.BOX)
    return [float(v) for v in _pixels(reduced)]


def _best_shift(a: list[float], b: list[float], limit: int) -> int:
    """Shift ``s`` minimising mean |a[i] - b[i - s]| (b moved by s)."""
    if not any(a) or not any(b):
        return 0
    best, best_cost = 0, float("inf")
    n = min(len(a), len(b))
    for shift in range(-limit, limit + 1):
        lo = max(0, shift)
        hi = min(n, n + shift)
        if hi - lo < n // 2:
            continue
        cost = 0.0
        for i in range(lo, hi):
            cost += abs(a[i] - b[i - shift])
        cost /= hi - lo
        # Prefer no shift on ties: jitter-free renders should stay put.
        if cost < best_cost - 1e-9 or (abs(cost - best_cost) <= 1e-9 and abs(shift) < abs(best)):
            best, best_cost = shift, cost
    return best


def register(left: Any, right: Any) -> tuple[int, int]:
    """Estimate the (dx, dy) that moves ``right`` onto ``left``."""
    limit_x = max(2, int(left.width * MAX_SHIFT))
    limit_y = max(2, int(left.height * MAX_SHIFT))
    dx = _best_shift(_profile(left, "x"), _profile(right, "x"), limit_x)
    dy = _best_shift(_profile(left, "y"), _profile(right, "y"), limit_y)
    return dx, dy


def _shifted(image: Any, dx: int, dy: int, size: tuple[int, int]) -> Any:
    from PIL import Image

    canvas = Image.new("L", size, 255)
    canvas.paste(image, (dx, dy))
    return canvas


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class PixelDiff:
    left: Any  # L image
    right: Any  # L image, registered onto left
    removed: Any  # L mask 0/255
    added: Any  # L mask 0/255
    offset: tuple[int, int]
    scaled: bool


#: Pages are analysed at most this wide; scans at 300 dpi are downscaled,
#: which also makes every threshold below resolution independent.
ANALYSIS_WIDTH = 1100
#: Gaussian radius applied to both pages before comparing (pixels).
PRE_BLUR = 1.0
#: Grey level below which a pixel is ink.
INK_LEVEL = 170
#: A region is kept when its changed pixels are at least this share of the
#: ink inside it. Edge residue from blur, JPEG noise or a sub-pixel shift is a
#: thin rim around ink that exists on both pages; a real edit is mostly new ink.
MIN_CHANGE_SHARE = 0.1


def diff_images(left_rgb: Any, right_rgb: Any, options: VisualOptions | None = None) -> PixelDiff:
    from PIL import Image, ImageChops, ImageFilter

    options = options or VisualOptions()
    left = left_rgb.convert("L")
    right = right_rgb.convert("L")
    if left.width > ANALYSIS_WIDTH:
        factor = ANALYSIS_WIDTH / left.width
        left = left.resize((ANALYSIS_WIDTH, max(1, round(left.height * factor))), Image.LANCZOS)
    scaled = False
    if right.size != left.size:
        # Same page at another resolution or paper size (A4 vs Letter export,
        # a rescaled scan): compare at the left page's size.
        native = right_rgb.size
        scaled = abs(native[0] / native[1] - left.width / left.height) > 0.01
        right = right.resize(left.size, Image.LANCZOS)

    dx = dy = 0
    if options.register:
        dx, dy = register(left, right)
        if dx or dy:
            right = _shifted(right, dx, dy, left.size)

    # Blur both pages the same way: a sharp render and a soft scan of the
    # same text then look alike, while added or removed ink still stands out.
    sharp_left, sharp_right = left, right
    left = left.filter(ImageFilter.GaussianBlur(PRE_BLUR))
    right = right.filter(ImageFilter.GaussianBlur(PRE_BLUR))

    # Neighbourhood minimum = darkest pixel within 1px: ink spread by 1px.
    left_spread = left.filter(ImageFilter.MinFilter(3))
    right_spread = right.filter(ImageFilter.MinFilter(3))
    threshold = options.tolerance

    def mask(darker: Any, reference_spread: Any) -> Any:
        # Ink in ``darker`` that is darker than anything nearby in the
        # reference image.
        delta = ImageChops.subtract(reference_spread, darker).point(
            lambda v: 255 if v > threshold else 0
        )
        ink = darker.point(lambda v: 255 if v < INK_LEVEL else 0)
        return ImageChops.multiply(delta, ink)

    removed = mask(left, right_spread)
    added = mask(right, left_spread)
    return PixelDiff(sharp_left, sharp_right, removed, added, (dx, dy), scaled)


def _regions(diff: PixelDiff) -> list[tuple[int, int, int, int, str, float]]:
    """Connected changed areas in pixels: (x0, y0, x1, y1, kind, density)."""
    from PIL import Image

    width, height = diff.left.size
    cols = (width + CELL - 1) // CELL
    rows = (height + CELL - 1) // CELL

    def pooled(mask: Any) -> list[int]:
        # Box-average each cell, then count it if any pixel inside changed.
        padded = Image.new("L", (cols * CELL, rows * CELL), 0)
        padded.paste(mask, (0, 0))
        small = padded.resize((cols, rows), Image.BOX)
        return list(_pixels(small))

    removed = pooled(diff.removed)
    added = pooled(diff.added)
    # Changed-pixel counts per cell (approximation from the mean).
    per_cell = CELL * CELL
    counts = [round((r + a) / 255 * per_cell) for r, a in zip(removed, added)]
    flagged = [c > 0 for c in counts]

    seen = [False] * len(flagged)
    regions: list[tuple[int, int, int, int, str, float]] = []
    for start, on in enumerate(flagged):
        if not on or seen[start]:
            continue
        queue = deque([start])
        seen[start] = True
        cells = []
        while queue:
            index = queue.popleft()
            cells.append(index)
            cy, cx = divmod(index, cols)
            # 8-neighbourhood plus a one-cell bridge: characters of one word
            # and nearby strokes become one region.
            for ny in range(cy - 2, cy + 3):
                if ny < 0 or ny >= rows:
                    continue
                for nx in range(cx - 2, cx + 3):
                    if nx < 0 or nx >= cols:
                        continue
                    neighbour = ny * cols + nx
                    if flagged[neighbour] and not seen[neighbour]:
                        seen[neighbour] = True
                        queue.append(neighbour)
        pixels = sum(counts[i] for i in cells)
        if pixels < MIN_PIXELS:
            continue
        xs = [i % cols for i in cells]
        ys = [i // cols for i in cells]
        x0, x1 = min(xs) * CELL, min(width, (max(xs) + 1) * CELL)
        y0, y1 = min(ys) * CELL, min(height, (max(ys) + 1) * CELL)
        box = (x0, y0, x1, y1)
        ink = max(_ink(diff.left.crop(box)), _ink(diff.right.crop(box)), 1)
        changed = diff.removed.crop(box).histogram()[255] + diff.added.crop(box).histogram()[255]
        if changed < MIN_CHANGE_SHARE * ink:
            continue
        rem = sum(removed[i] for i in cells)
        add = sum(added[i] for i in cells)
        if rem and add:
            kind = "replace" if min(rem, add) > 0.15 * max(rem, add) else ("delete" if rem > add else "insert")
        else:
            kind = "delete" if rem else "insert"
        area = max((x1 - x0) * (y1 - y0), 1)
        regions.append((x0, y0, x1, y1, kind, min(pixels / area, 1.0)))
    return _merge(regions)


def _merge(
    regions: list[tuple[int, int, int, int, str, float]],
) -> list[tuple[int, int, int, int, str, float]]:
    """Merge regions that overlap, so one edit is one box."""
    merged = True
    regions = list(regions)
    while merged:
        merged = False
        out: list[tuple[int, int, int, int, str, float]] = []
        for region in regions:
            for index, other in enumerate(out):
                if (
                    region[0] <= other[2]
                    and other[0] <= region[2]
                    and region[1] <= other[3]
                    and other[1] <= region[3]
                ):
                    kind = region[4] if region[4] == other[4] else "replace"
                    out[index] = (
                        min(region[0], other[0]),
                        min(region[1], other[1]),
                        max(region[2], other[2]),
                        max(region[3], other[3]),
                        kind,
                        max(region[5], other[5]),
                    )
                    merged = True
                    break
            else:
                out.append(region)
        regions = out
    regions.sort(key=lambda r: (r[1], r[0]))
    return regions


def _ink(image: Any) -> int:
    histogram = image.point(lambda v: 255 if v < 200 else 0).histogram()
    return histogram[255]


def compare_images(
    left_rgb: Any,
    right_rgb: Any,
    *,
    page_size: tuple[float, float],
    pair: int = 0,
    left_index: int | None = 0,
    right_index: int | None = 0,
    options: VisualOptions | None = None,
) -> tuple[VisualPage, PixelDiff]:
    diff = diff_images(left_rgb, right_rgb, options)
    width, height = diff.left.size
    scale_x = page_size[0] / width if page_size[0] else 1.0
    scale_y = page_size[1] / height if page_size[1] else 1.0

    regions = [
        VisualRegion(
            x0=round(x0 * scale_x, 2),
            top=round(y0 * scale_y, 2),
            x1=round(x1 * scale_x, 2),
            bottom=round(y1 * scale_y, 2),
            kind=kind,
            density=round(density, 3),
        )
        for x0, y0, x1, y1, kind, density in _regions(diff)
    ]
    changed = diff.removed.histogram()[255] + diff.added.histogram()[255]
    ink = max(_ink(diff.left) + _ink(diff.right), 1)
    page = VisualPage(
        pair=pair,
        left=left_index,
        right=right_index,
        changed_ratio=round(min(changed / ink, 1.0), 4) if regions else 0.0,
        regions=regions,
        offset=(round(diff.offset[0] * scale_x, 2), round(diff.offset[1] * scale_y, 2)),
        scaled=diff.scaled,
    )
    return page, diff


def overlay_image(diff: PixelDiff) -> Any:
    """Both pages in one image: shared ink grey, removed red, added green."""
    from PIL import Image, ImageChops

    # Light grey base: the darker of the two pages, faded.
    base = ImageChops.darker(diff.left, diff.right).point(lambda v: 255 - (255 - v) * 0.45)
    rgb = Image.merge("RGB", (base, base, base))
    red = Image.new("RGB", rgb.size, (224, 27, 36))
    green = Image.new("RGB", rgb.size, (38, 162, 105))
    rgb.paste(red, (0, 0), diff.removed)
    rgb.paste(green, (0, 0), diff.added)
    return rgb


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #

Renderer = Callable[[Document, int, int], Any]


def _default_renderer(document: Document, index: int, dpi: int) -> Any:
    from .render import render_page

    return render_page(document, index, dpi)


def _render_dpi(document: Document, dpi: int) -> int:
    # Image pages are in pixels: render them at (close to) native size, but
    # not larger than a page rendered at ``dpi`` would be.
    if document.kind == "image":
        return 72
    return dpi


def compare_pair(
    left: Document,
    right: Document,
    pair_index: int,
    pair: PagePair,
    options: VisualOptions | None = None,
    renderer: Renderer = _default_renderer,
) -> tuple[VisualPage, PixelDiff | None]:
    options = options or VisualOptions()
    if pair.left is None or pair.right is None:
        # A page that exists on one side only is entirely added/removed.
        index = pair.left if pair.left is not None else pair.right
        document = left if pair.left is not None else right
        page = document.pages[index]  # type: ignore[index]
        kind = "delete" if pair.left is not None else "insert"
        region = VisualRegion(0.0, 0.0, page.width, page.height, kind, 1.0)
        return (
            VisualPage(pair_index, pair.left, pair.right, changed_ratio=1.0, regions=[region]),
            None,
        )

    left_image = renderer(left, pair.left, _render_dpi(left, options.dpi))
    right_image = renderer(right, pair.right, _render_dpi(right, options.dpi))
    if left.kind == "image" and max(left_image.size) > 2400:
        # Very large scans: compare at a reading resolution.
        factor = 2400 / max(left_image.size)
        left_image = left_image.resize(
            (round(left_image.width * factor), round(left_image.height * factor))
        )
    page = left.pages[pair.left]
    return compare_images(
        left_image,
        right_image,
        page_size=(page.width, page.height),
        pair=pair_index,
        left_index=pair.left,
        right_index=pair.right,
        options=options,
    )


def compare_documents(
    left: Document,
    right: Document,
    page_map: Sequence[PagePair],
    options: VisualOptions | None = None,
    renderer: Renderer = _default_renderer,
) -> list[VisualPage]:
    pages: list[VisualPage] = []
    for index, pair in enumerate(page_map):
        page, _ = compare_pair(left, right, index, pair, options, renderer)
        pages.append(page)
    return pages
