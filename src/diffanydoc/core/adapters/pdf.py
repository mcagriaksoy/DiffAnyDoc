"""PDF adapter: text lines with word coordinates, using pdfplumber (MIT).

Pages without a text layer (scans) go through OCR when an engine is installed,
see :mod:`diffanydoc.core.ocr`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..layout import make_line, merge_hyphenation
from ..model import Block, Document, Page
from .base import AdapterError, LoadOptions

#: Words whose top differs by less than this are on the same line.
_LINE_TOLERANCE_PT = 2.5
#: A page with fewer extracted characters than this is treated as a scan.
_MIN_TEXT_CHARS = 8


class PdfAdapter:
    name = "pdf"
    extensions = (".pdf",)

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def load(self, path: Path, options: LoadOptions | None = None) -> Document:
        options = options or LoadOptions()
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise AdapterError("pdfplumber is not installed") from exc

        try:
            with pdfplumber.open(str(path)) as pdf:
                meta = _clean_meta(pdf.metadata or {})
                pages = [
                    _build_page(index, page) for index, page in enumerate(pdf.pages)
                ]
        except Exception as exc:  # pdfminer raises a wide range of errors
            raise AdapterError(f"cannot read PDF {path.name!r}: {exc}") from exc

        document = Document(path=path, kind="pdf", pages=pages, meta=meta)
        _apply_ocr(document, options)
        return document


def _apply_ocr(document: Document, options: LoadOptions) -> None:
    if options.ocr == "off":
        empty = [p.index for p in document.pages if p.source == "none"]
        if empty:
            document.warnings.append({"code": "no_text_layer", "pages": empty})
        return

    targets = [
        page
        for page in document.pages
        if options.ocr == "force" or page.source == "none"
    ]
    if not targets:
        return

    from .. import ocr

    engine = ocr.default_engine()
    if engine is None:
        document.warnings.append(
            {"code": "ocr_unavailable", "pages": [p.index for p in targets]}
        )
        return

    from ..render import render_page

    lang = options.ocr_lang or engine.default_language()
    done: list[int] = []
    for page in targets:
        try:
            blocks = ocr.recognize_page(
                engine,
                document.path,
                page.index,
                lambda dpi, index=page.index: render_page(document, index, dpi),
                page_width=page.width,
                page_height=page.height,
                dpi=options.ocr_dpi,
                lang=lang,
            )
        except ocr.OcrError as exc:
            document.warnings.append(
                {"code": "ocr_failed", "pages": [page.index], "message": str(exc)}
            )
            continue
        page.blocks = merge_hyphenation(blocks)
        page.source = "ocr"
        done.append(page.index)
    if done:
        document.warnings.append(
            {"code": "ocr_used", "pages": done, "engine": engine.name, "lang": lang}
        )
        document.meta["ocr_pages"] = len(done)


def _clean_meta(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in meta.items():
        if value in (None, ""):
            continue
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        out[str(key)] = str(value)
    return out


def _build_page(index: int, page: Any) -> Page:
    words = page.extract_words(
        use_text_flow=False,
        keep_blank_chars=False,
        extra_attrs=["size", "fontname"],
    )
    blocks = merge_hyphenation(_group_lines(words, index))
    chars = sum(len(b.text.strip()) for b in blocks)
    width, height = float(page.width), float(page.height)
    return Page(
        index=index,
        width=width,
        height=height,
        blocks=blocks,
        source="none" if _looks_scanned(page, chars, width * height) else "text",
    )


def _looks_scanned(page: Any, chars: int, area: float) -> bool:
    """No text layer worth the name, and the page is (mostly) a picture.

    A page with no text at all is always a candidate (it may be a scan or
    text drawn as outlines). A page with a few characters only counts when a
    large image covers it: scanners often add a page number or an invisible
    one-word layer on top of the scan.
    """
    if chars == 0:
        return True
    if chars >= _MIN_TEXT_CHARS:
        return False
    try:
        images = page.images
    except Exception:  # pragma: no cover - pdfminer edge cases
        return False
    covered = 0.0
    for image in images:
        try:
            covered += abs(float(image["x1"]) - float(image["x0"])) * abs(
                float(image["bottom"]) - float(image["top"])
            )
        except (KeyError, TypeError, ValueError):
            continue
    return area > 0 and covered >= 0.3 * area


def _group_lines(words: Iterable[dict[str, Any]], page_index: int) -> list[Block]:
    """Group words into visual lines, keeping one span per word."""
    words = sorted(words, key=lambda w: (round(float(w["top"]), 1), float(w["x0"])))
    lines: list[list[dict[str, Any]]] = []
    for word in words:
        if lines:
            current = lines[-1]
            top = sum(float(w["top"]) for w in current) / len(current)
            if abs(float(word["top"]) - top) <= _LINE_TOLERANCE_PT:
                current.append(word)
                continue
        lines.append([word])

    blocks: list[Block] = []
    for line in lines:
        line.sort(key=lambda w: float(w["x0"]))
        block = make_line(
            [
                (
                    str(w["text"]),
                    (float(w["x0"]), float(w["top"]), float(w["x1"]), float(w["bottom"])),
                )
                for w in line
            ],
            page_index,
            style=_style(line),
            source_ref={"line": len(blocks)},
        )
        blocks.append(block)
    return blocks


def _style(line: list[dict[str, Any]]) -> dict[str, Any]:
    sizes = [float(w.get("size") or 0.0) for w in line]
    fonts = [str(w.get("fontname") or "") for w in line]
    fonts = [f for f in fonts if f]
    font = max(set(fonts), key=fonts.count) if fonts else ""
    # Subset prefixes ("ABCDEF+Helvetica") differ between exports of the same
    # document; strip them so formatting comparison sees the real font.
    if "+" in font[:8]:
        font = font.split("+", 1)[1]
    lower = font.lower()
    return {
        "size": round(sorted(sizes)[len(sizes) // 2], 2),
        "font": font,
        "bold": "bold" in lower or "black" in lower or "heavy" in lower,
        "italic": "italic" in lower or "oblique" in lower,
    }
