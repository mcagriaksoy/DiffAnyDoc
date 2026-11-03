"""Image adapter: scans, screenshots and photos of documents.

Each frame is one page whose units are pixels. Text comes from OCR when an
engine is installed; the visual (pixel) comparison works either way.
"""

from __future__ import annotations

from pathlib import Path

from ..model import Document, Page
from ..render import IMAGE_EXTENSIONS, render_page
from .base import AdapterError, LoadOptions

#: Images are OCR'd at their own resolution, upscaled when they are small.
_MIN_OCR_WIDTH = 1600


class ImageAdapter:
    name = "image"
    extensions = IMAGE_EXTENSIONS

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def load(self, path: Path, options: LoadOptions | None = None) -> Document:
        options = options or LoadOptions()
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise AdapterError("Pillow is not installed") from exc

        try:
            with Image.open(path) as image:
                frames = getattr(image, "n_frames", 1)
                pages = []
                for index in range(frames):
                    image.seek(index)
                    width, height = ImageOps.exif_transpose(image).size
                    pages.append(
                        Page(index=index, width=float(width), height=float(height), source="none")
                    )
                meta = {
                    "format": image.format or path.suffix.lstrip(".").upper(),
                    "mode": image.mode,
                    "frames": frames,
                }
                dpi = image.info.get("dpi")
                if dpi:
                    meta["dpi"] = round(float(dpi[0]))
        except Exception as exc:  # Pillow raises many error types
            raise AdapterError(f"cannot read image {path.name!r}: {exc}") from exc

        document = Document(path=path, kind="image", pages=pages, meta=meta)
        if options.ocr != "off":
            _ocr(document, options)
        return document


def _ocr(document: Document, options: LoadOptions) -> None:
    from .. import ocr

    engine = ocr.default_engine()
    if engine is None:
        document.warnings.append(
            {"code": "ocr_unavailable", "pages": [p.index for p in document.pages]}
        )
        return
    lang = options.ocr_lang or engine.default_language()
    done: list[int] = []
    for page in document.pages:
        # dpi is relative to page units (pixels = 72 "dpi"): upscale small
        # screenshots, which Tesseract reads much better at ~2x.
        dpi = 72 if page.width >= _MIN_OCR_WIDTH else min(216, round(72 * _MIN_OCR_WIDTH / max(page.width, 1)))
        try:
            page.blocks = ocr.recognize_page(
                engine,
                document.path,
                page.index,
                lambda scale_dpi, index=page.index: render_page(document, index, scale_dpi),
                page_width=page.width,
                page_height=page.height,
                dpi=dpi,
                lang=lang,
            )
        except ocr.OcrError as exc:
            document.warnings.append(
                {"code": "ocr_failed", "pages": [page.index], "message": str(exc)}
            )
            continue
        page.source = "ocr" if page.blocks else "none"
        done.append(page.index)
    if done:
        document.warnings.append(
            {"code": "ocr_used", "pages": done, "engine": engine.name, "lang": lang}
        )
