"""Image adapter: PNG, JPEG, TIFF, BMP and WebP files.

Scanned contracts and screenshots often arrive as raw image files rather than
PDFs. This adapter wraps each image frame into a :class:`~diffanydoc.core.model.Page`
whose dimensions are expressed in PDF points (72 pt/inch), so both the visual
pixel diff and the Tesseract OCR layer work identically on images and PDFs.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ..model import Document, Page
from .base import AdapterError

_IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
)


class ImageAdapter:
    name = "image"
    extensions = _IMAGE_EXTENSIONS

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def load(self, path: Path) -> Document:
        try:
            with Image.open(path) as img:
                fmt = (img.format or path.suffix.lstrip(".")).upper()
                n_frames = getattr(img, "n_frames", 1) or 1
                pages: list[Page] = []
                for index in range(n_frames):
                    if n_frames > 1:
                        img.seek(index)
                    dpi_info = img.info.get("dpi")
                    dpi_x = float(dpi_info[0]) if dpi_info and dpi_info[0] > 0 else 96.0
                    dpi_y = float(dpi_info[1]) if dpi_info and dpi_info[1] > 0 else 96.0
                    width_pt = round(img.width * 72.0 / dpi_x, 2)
                    height_pt = round(img.height * 72.0 / dpi_y, 2)
                    pages.append(
                        Page(
                            index=index,
                            width=width_pt,
                            height=height_pt,
                            blocks=[],
                        )
                    )
        except (UnidentifiedImageError, OSError) as exc:
            raise AdapterError(f"cannot read image {path.name!r}: {exc}") from exc

        return Document(
            path=path,
            kind="image",
            pages=pages,
            meta={"format": fmt, "frames": len(pages)},
        )
