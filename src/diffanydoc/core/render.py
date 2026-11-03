"""Page rasterisation shared by the viewer, the visual diff and OCR.

pdfium is not thread-safe, so every call goes through one process-wide lock.
Rendered pages are cached in memory (bounded) because the viewer, the visual
diff and OCR often ask for the same page at the same resolution.
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .model import Document

_LOCK = threading.RLock()
_CACHE: "OrderedDict[tuple[str, float, int, int], Any]" = OrderedDict()
_CACHE_LIMIT = 48

#: File types the image adapter reads; also the ones we can render directly.
IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".webp",
)


class RenderError(RuntimeError):
    pass


def _key(path: Path, index: int, dpi: int) -> tuple[str, float, int, int]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (str(path), mtime, index, dpi)


def render_page(document: Document | Path | str, index: int, dpi: int = 110) -> Any:
    """Return page ``index`` as an RGB :class:`PIL.Image.Image`.

    ``dpi`` is relative to the page's own units: 72 units per inch for PDF,
    and for images the page *is* the pixel grid, so ``dpi=72`` gives the
    original size.
    """
    if isinstance(document, Document):
        path, kind = document.path, document.kind
    else:
        path = Path(document)
        kind = "pdf" if path.suffix.lower() == ".pdf" else "image"
    key = _key(path, index, dpi)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached.copy()
        if kind == "pdf":
            image = _render_pdf(path, index, dpi)
        elif kind == "image":
            image = _render_image(path, index, dpi)
        else:
            raise RenderError(f"{kind} files cannot be rendered as pages")
        _CACHE[key] = image
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
        return image.copy()


def render_png(document: Document | Path | str, index: int, dpi: int = 110) -> bytes:
    image = render_page(document, index, dpi)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _render_pdf(path: Path, index: int, dpi: int) -> Any:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        if index < 0 or index >= len(document):
            raise RenderError(f"page {index} does not exist")
        page = document[index]
        try:
            bitmap = page.render(scale=dpi / 72)
            try:
                return bitmap.to_pil().convert("RGB")
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _render_image(path: Path, index: int, dpi: int) -> Any:
    from PIL import Image, ImageOps

    with Image.open(path) as source:
        frames = getattr(source, "n_frames", 1)
        if index < 0 or index >= frames:
            raise RenderError(f"frame {index} does not exist")
        source.seek(index)
        image = ImageOps.exif_transpose(source.convert("RGBA"))
        # Transparent areas render as paper (white), like a viewer would.
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image).convert("RGB")
    if dpi != 72:
        scale = dpi / 72
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.LANCZOS)
    return image


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
