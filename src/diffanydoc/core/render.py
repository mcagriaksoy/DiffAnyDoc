"""Page rasterisation shared by the page viewer and the visual diff.

pdfium is not safe to call from several threads at once, so every render goes
through one process-wide lock. Both the PNG endpoint and the pixel comparison
use this module, which keeps the two from racing each other.
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image

#: Images are large (a page at 96 dpi is ~2.3 MB in RGB); keep few of them.
_MAX_IMAGES = 12
_MAX_PNGS = 96

_LOCK = threading.Lock()
_IMAGES: "OrderedDict[tuple[str, int, int], Image.Image]" = OrderedDict()
_PNGS: "OrderedDict[tuple[str, int, int], bytes]" = OrderedDict()


def _key(path: Path, index: int, dpi: int) -> tuple[str, int, int]:
    return (str(path), int(index), int(dpi))


def render_page(path: str | Path, index: int, dpi: int = 96) -> Image.Image:
    """Render one PDF page to an RGB image. Cached, bounded, thread-safe."""
    key = _key(Path(path), index, dpi)
    cached = _IMAGES.get(key)
    if cached is not None:
        _IMAGES.move_to_end(key)
        return cached

    import pypdfium2 as pdfium

    with _LOCK:
        cached = _IMAGES.get(key)
        if cached is not None:
            _IMAGES.move_to_end(key)
            return cached

        document = pdfium.PdfDocument(str(path))
        try:
            if index < 0 or index >= len(document):
                raise IndexError(f"page {index} does not exist")
            page = document[index]
            bitmap = page.render(scale=max(dpi, 24) / 72)
            try:
                image = bitmap.to_pil().convert("RGB")
            finally:
                bitmap.close()
        finally:
            document.close()

        _IMAGES[key] = image
        _IMAGES.move_to_end(key)
        while len(_IMAGES) > _MAX_IMAGES:
            _IMAGES.popitem(last=False)
    return image


def render_page_png(path: str | Path, index: int, dpi: int = 96) -> bytes:
    """PNG bytes for the page viewer."""
    key = _key(Path(path), index, dpi)
    cached = _PNGS.get(key)
    if cached is not None:
        _PNGS.move_to_end(key)
        return cached

    buffer = io.BytesIO()
    render_page(path, index, dpi).save(buffer, format="PNG")
    data = buffer.getvalue()

    _PNGS[key] = data
    _PNGS.move_to_end(key)
    while len(_PNGS) > _MAX_PNGS:
        _PNGS.popitem(last=False)
    return data


def clear_cache() -> None:
    """Drop rendered pages (tests and low-memory situations)."""
    with _LOCK:
        _IMAGES.clear()
        _PNGS.clear()
