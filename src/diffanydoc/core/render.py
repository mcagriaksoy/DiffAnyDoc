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

from PIL import Image, ImageDraw, ImageFont

#: Images are large (a page at 96 dpi is ~2.3 MB in RGB); keep few of them.
_MAX_IMAGES = 12
_MAX_PNGS = 96

_LOCK = threading.Lock()
_IMAGES: "OrderedDict[tuple[str, int, int], Image.Image]" = OrderedDict()
_PNGS: "OrderedDict[tuple[str, int, int], bytes]" = OrderedDict()


def _key(path: Path, index: int, dpi: int) -> tuple[str, int, int]:
    return (str(path), int(index), int(dpi))


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def is_renderable_path(path: str | Path) -> bool:
    """Whether a file on disk can be rasterised as page images."""
    from .adapters import supported_extensions

    suffix = Path(path).suffix.lower()
    return suffix == ".pdf" or suffix in _IMAGE_SUFFIXES or suffix in supported_extensions()


def _get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    font_names = (
        ["LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf", "Cantarell-Bold.otf"]
        if bold
        else ["LiberationSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf", "Cantarell-Regular.otf"]
    )
    for name in font_names:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, ImportError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_sheet_page(path: str | Path, index: int, dpi: int = 96) -> Image.Image:
    """Render one paginated page of an office/text document into an A4 sheet image."""
    from .adapters import load
    from .layout import paginate_document

    target = Path(path)
    doc = load(target)
    doc = paginate_document(doc)

    if index < 0 or index >= len(doc.pages):
        raise IndexError(f"page {index} does not exist (total: {len(doc.pages)})")

    page = doc.pages[index]
    width_pt = page.width or 595.0
    height_pt = page.height or 842.0
    scale = max(dpi, 24) / 72.0

    img_w = max(1, round(width_pt * scale))
    img_h = max(1, round(height_pt * scale))

    image = Image.new("RGB", (img_w, img_h), "#ffffff")
    draw = ImageDraw.Draw(image)

    title_font = _get_font(max(12, round(15 * scale)), bold=True)
    body_font = _get_font(max(9, round(10.5 * scale)), bold=False)
    bold_body_font = _get_font(max(9, round(10.5 * scale)), bold=True)
    footer_font = _get_font(max(8, round(8.5 * scale)), bold=False)

    for block in page.blocks:
        if not block.bbox:
            continue
        bx0, btop, bx1, _ = block.bbox
        px0 = bx0 * scale
        ptop = btop * scale

        if block.kind == "image":
            img_data = block.source_ref.get("data")
            pic_w = max(1, round((bx1 - bx0) * scale))
            pic_h = max(1, round((block.bbox[3] - btop) * scale))
            pasted = False
            if img_data:
                try:
                    import io
                    with Image.open(io.BytesIO(img_data)) as pic:
                        pic_rgb = pic.convert("RGB")
                        if (pic_w, pic_h) != pic_rgb.size:
                            pic_rgb = pic_rgb.resize((pic_w, pic_h), Image.Resampling.LANCZOS)
                        image.paste(pic_rgb, (round(px0), round(ptop)))
                        pasted = True
                except Exception:
                    pasted = False
            if not pasted:
                draw.rectangle([px0, ptop, px0 + pic_w, ptop + pic_h], outline="#d0d7de", fill="#f6f8fa")
                name = block.source_ref.get("name") or "Image"
                draw.text((px0 + 6 * scale, ptop + 6 * scale), f"[{name}]", fill="#57606a", font=body_font)
            continue

        if block.kind == "table" and block.children:
            ty = ptop
            for row in block.children:
                cells = row.cells or [c.text for c in row.children] or [row.text]
                if not cells:
                    continue
                cell_w = (bx1 - bx0) * scale / max(len(cells), 1)
                row_h = 20.0 * scale
                tx = px0
                for cell_txt in cells:
                    draw.rectangle([tx, ty, tx + cell_w, ty + row_h], outline="#d0d7de", fill="#fbfcfd")
                    draw.text((tx + 4 * scale, ty + 3 * scale), str(cell_txt)[:50], fill="#24292e", font=body_font)
                    tx += cell_w
                ty += row_h
            continue

        if block.cells is not None:
            cell_w = (bx1 - bx0) * scale / max(len(block.cells), 1)
            row_h = 20.0 * scale
            tx = px0
            for cell_txt in block.cells:
                draw.rectangle([tx, ptop, tx + cell_w, ptop + row_h], outline="#d0d7de", fill="#fbfcfd")
                draw.text((tx + 4 * scale, ptop + 3 * scale), str(cell_txt)[:50], fill="#24292e", font=body_font)
                tx += cell_w
            continue

        is_heading = bool(block.style.get("heading") or (block.style.get("bold") and len(block.text) < 80))
        font = title_font if is_heading else (bold_body_font if block.style.get("bold") else body_font)
        text_color = "#111827" if is_heading else "#24292e"

        line_spacing = 22.0 * scale if is_heading else 15.0 * scale
        text = block.text
        if not text:
            continue

        max_chars = max(int(((bx1 - bx0) * scale) / (6.0 * scale)), 15)
        words = text.split()
        current_line: list[str] = []
        cur_len = 0
        cur_y = ptop

        for w in words:
            if cur_len + len(w) + 1 > max_chars and current_line:
                draw.text((px0, cur_y), " ".join(current_line), fill=text_color, font=font)
                cur_y += line_spacing
                current_line = [w]
                cur_len = len(w)
            else:
                current_line.append(w)
                cur_len += len(w) + 1
        if current_line:
            draw.text((px0, cur_y), " ".join(current_line), fill=text_color, font=font)

    footer_text = f"{index + 1} / {len(doc.pages)}"
    draw.text(
        ((width_pt - 54.0 - 20.0) * scale, (height_pt - 36.0) * scale),
        footer_text,
        fill="#9ca3af",
        font=footer_font,
    )

    return image


def render_page(path: str | Path, index: int, dpi: int = 96) -> Image.Image:
    """Render one PDF page or image frame to an RGB image. Cached, bounded, thread-safe."""
    target = Path(path)
    key = _key(target, index, dpi)
    cached = _IMAGES.get(key)
    if cached is not None:
        _IMAGES.move_to_end(key)
        return cached

    with _LOCK:
        cached = _IMAGES.get(key)
        if cached is not None:
            _IMAGES.move_to_end(key)
            return cached

        if target.suffix.lower() in _IMAGE_SUFFIXES:
            with Image.open(target) as raw:
                n_frames = getattr(raw, "n_frames", 1) or 1
                if index < 0 or index >= n_frames:
                    raise IndexError(f"page {index} does not exist")
                if n_frames > 1:
                    raw.seek(index)
                dpi_info = raw.info.get("dpi")
                if dpi_info and dpi_info[0] >= 140.0 and target.suffix.lower() in (".tif", ".tiff"):
                    src_dpi_x = float(dpi_info[0])
                    src_dpi_y = float(dpi_info[1]) if dpi_info[1] > 0 else src_dpi_x
                else:
                    src_dpi_x = 96.0
                    src_dpi_y = 96.0
                width_pt = raw.width * 72.0 / src_dpi_x
                height_pt = raw.height * 72.0 / src_dpi_y
                scale = max(dpi, 24) / 72.0
                out_w = max(1, round(width_pt * scale))
                out_h = max(1, round(height_pt * scale))
                image = raw.convert("RGB")
                if (out_w, out_h) != image.size:
                    image = image.resize((out_w, out_h), Image.Resampling.LANCZOS)
        elif target.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium

            document = pdfium.PdfDocument(str(target))
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
        else:
            image = render_sheet_page(target, index, dpi)

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
