"""Official printable PDF comparison report generator.

Pure-stdlib and Pillow only (MIT-CMU): zero copyleft dependencies, zero external
binaries (no ReportLab, no WeasyPrint, no wkhtmltopdf). Works 100% offline.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ...i18n import resolve_language, t
from ..model import DiffResult, Row

# Standard A4 at 150 DPI
PAGE_WIDTH = 1240
PAGE_HEIGHT = 1754
MARGIN_X = 60
MARGIN_Y = 50
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
BOTTOM_LIMIT = PAGE_HEIGHT - 60
ROW_HEIGHT = 26

# Palette (Adwaita / GNOME clean enterprise palette)
BG_WHITE = (255, 255, 255)
BG_CARD = (248, 250, 252)
BG_HEADER = (241, 245, 249)
BORDER_LIGHT = (226, 232, 240)
BORDER_CARD = (203, 213, 225)
TEXT_MAIN = (15, 23, 42)
TEXT_MUTED = (100, 116, 139)
TEXT_DIM = (148, 163, 184)
ACCENT_BLUE = (37, 99, 235)
ACCENT_BLUE_LIGHT = (239, 246, 255)

# Diff colors
DIFF_INS_BG = (220, 252, 231)
DIFF_INS_BORDER = (134, 239, 172)
DIFF_INS_TEXT = (22, 101, 52)

DIFF_DEL_BG = (254, 226, 226)
DIFF_DEL_BORDER = (252, 165, 165)
DIFF_DEL_TEXT = (153, 27, 27)

DIFF_MOD_BG = (254, 243, 199)
DIFF_MOD_BORDER = (252, 211, 77)
DIFF_MOD_TEXT = (146, 64, 14)

DIFF_SAME_BG = (255, 255, 255)
DIFF_SAME_BORDER = (241, 245, 249)

_FONT_CACHE: dict[tuple[int, bool, bool], ImageFont.ImageFont] = {}


def _get_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.ImageFont:
    """Load system font with fallbacks and caching."""
    key = (size, bold, mono)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    candidates: list[str] = []
    if mono:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
            "/System/Library/Fonts/Courier.dfont",
            "C:\\Windows\\Fonts\\consola.ttf",
            "C:\\Windows\\Fonts\\cour.ttf",
        ])
    elif bold:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
        ])
    else:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
        ])

    for path in candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _FONT_CACHE[key] = font
                return font
            except Exception:
                continue

    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _truncate_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> str:
    """Ensure text fits inside max_width pixels, truncating with ellipsis if needed."""
    if not text:
        return ""
    bbox = draw.textbbox((0, 0), text, font=font)
    if (bbox[2] - bbox[0]) <= max_width:
        return text

    ellipsis = "…"
    low, high = 0, len(text)
    best = ellipsis
    while low <= high:
        mid = (low + high) // 2
        cand = text[:mid] + ellipsis
        bb = draw.textbbox((0, 0), cand, font=font)
        if (bb[2] - bb[0]) <= max_width:
            best = cand
            low = mid + 1
        else:
            high = mid - 1
    return best


def render_pdf(
    result: DiffResult,
    language: str | None = None,
    max_pages: int = 100,
    diff_only: bool = False,
) -> bytes:
    """Render a comprehensive printable PDF comparison report."""
    lang = resolve_language(language)
    pages: list[Image.Image] = []

    font_title = _get_font(24, bold=True)
    font_sub = _get_font(13)
    font_h2 = _get_font(15, bold=True)
    font_h3 = _get_font(13, bold=True)
    font_body = _get_font(12)
    font_body_bold = _get_font(12, bold=True)
    font_code = _get_font(11, mono=True)
    font_caption = _get_font(10)
    font_metric = _get_font(24, bold=True)

    # Filter rows if diff_only is requested
    rows_to_render: list[Row] = []
    for r in result.rows:
        if diff_only and r.kind == "equal":
            continue
        rows_to_render.append(r)

    # Page 1: Cover Sheet & Executive Summary
    cur_img = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), BG_WHITE)
    cur_draw = ImageDraw.Draw(cur_img)
    pages.append(cur_img)

    y = MARGIN_Y

    # Header Bar on Page 1
    cur_draw.text((MARGIN_X, y), "DiffAnyDoc", fill=ACCENT_BLUE, font=font_title)
    tb_title = cur_draw.textbbox((MARGIN_X, y), "DiffAnyDoc", font=font_title)
    sep_x = tb_title[2] + 14
    cur_draw.text((sep_x, y + 4), "·  " + t("report.brand", lang).title() + " Report", fill=TEXT_MAIN, font=font_h2)
    y += 42

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    cur_draw.text(
        (MARGIN_X, y),
        t("report.pdf.generatedAt", lang, time=now_str) if "report.pdf.generatedAt" in t.__name__ else f"Generated: {now_str}  ·  Privacy-First Local Verification",
        fill=TEXT_MUTED,
        font=font_sub,
    )
    y += 28

    # Separator rule
    cur_draw.line([(MARGIN_X, y), (PAGE_WIDTH - MARGIN_X, y)], fill=BORDER_LIGHT, width=1)
    y += 20

    # Document Comparison Fingerprint Cards (Left & Right)
    card_w = (CONTENT_WIDTH - 20) // 2
    card_h = 135

    left_name = result.left_path.name
    right_name = result.right_path.name
    left_pages_cnt = max(len(result.left_pages), 1)
    right_pages_cnt = max(len(result.right_pages), 1)

    # Document A Card
    cur_draw.rounded_rectangle(
        [(MARGIN_X, y), (MARGIN_X + card_w, y + card_h)],
        radius=6,
        fill=BG_CARD,
        outline=BORDER_CARD,
        width=1,
    )
    cur_draw.text((MARGIN_X + 16, y + 12), "Document A (Base / Left)", fill=ACCENT_BLUE, font=font_h3)
    doc_a_name = _truncate_text(cur_draw, left_name, font_body_bold, card_w - 32)
    cur_draw.text((MARGIN_X + 16, y + 36), doc_a_name, fill=TEXT_MAIN, font=font_body_bold)
    meta_a = f"{result.left_kind.upper()}  ·  {left_pages_cnt} page(s)  ·  {result.stats.left_lines} lines"
    cur_draw.text((MARGIN_X + 16, y + 62), meta_a, fill=TEXT_MUTED, font=font_body)
    hash_a = f"SHA-256: {result.left_sha256[:20]}…{result.left_sha256[-8:]}" if result.left_sha256 else "SHA-256: none"
    cur_draw.text((MARGIN_X + 16, y + 88), hash_a, fill=TEXT_DIM, font=font_code)

    # Document B Card
    bx = MARGIN_X + card_w + 20
    cur_draw.rounded_rectangle(
        [(bx, y), (bx + card_w, y + card_h)],
        radius=6,
        fill=BG_CARD,
        outline=BORDER_CARD,
        width=1,
    )
    cur_draw.text((bx + 16, y + 12), "Document B (Target / Right)", fill=ACCENT_BLUE, font=font_h3)
    doc_b_name = _truncate_text(cur_draw, right_name, font_body_bold, card_w - 32)
    cur_draw.text((bx + 16, y + 36), doc_b_name, fill=TEXT_MAIN, font=font_body_bold)
    meta_b = f"{result.right_kind.upper()}  ·  {right_pages_cnt} page(s)  ·  {result.stats.right_lines} lines"
    cur_draw.text((bx + 16, y + 62), meta_b, fill=TEXT_MUTED, font=font_body)
    hash_b = f"SHA-256: {result.right_sha256[:20]}…{result.right_sha256[-8:]}" if result.right_sha256 else "SHA-256: none"
    cur_draw.text((bx + 16, y + 88), hash_b, fill=TEXT_DIM, font=font_code)

    y += card_h + 16

    # Executive Summary Metrics (4 metric tiles)
    tile_w = (CONTENT_WIDTH - 30) // 4
    tile_h = 75

    metrics = [
        ("Similarity", f"{result.stats.similarity * 100:.1f}%", ACCENT_BLUE, ACCENT_BLUE_LIGHT),
        ("Added", f"+{result.stats.added}", DIFF_INS_TEXT, DIFF_INS_BG),
        ("Removed", f"-{result.stats.removed}", DIFF_DEL_TEXT, DIFF_DEL_BG),
        ("Modified", f"~{result.stats.changed}", DIFF_MOD_TEXT, DIFF_MOD_BG),
    ]

    for i, (label, val, text_c, bg_c) in enumerate(metrics):
        tx = MARGIN_X + i * (tile_w + 10)
        cur_draw.rounded_rectangle(
            [(tx, y), (tx + tile_w, y + tile_h)],
            radius=6,
            fill=bg_c,
            outline=BORDER_LIGHT,
            width=1,
        )
        cur_draw.text((tx + 14, y + 10), label, fill=TEXT_MUTED, font=font_caption)
        cur_draw.text((tx + 14, y + 30), val, fill=text_c, font=font_metric)

    y += tile_h + 16

    # Status Banner
    banner_h = 36
    if result.byte_identical:
        cur_draw.rounded_rectangle(
            [(MARGIN_X, y), (PAGE_WIDTH - MARGIN_X, y + banner_h)],
            radius=6,
            fill=DIFF_INS_BG,
            outline=DIFF_INS_BORDER,
            width=1,
        )
        cur_draw.text(
            (MARGIN_X + 16, y + 8),
            "✔  Files are 100% byte-identical (identical SHA-256 fingerprint, 0 differences).",
            fill=DIFF_INS_TEXT,
            font=font_body_bold,
        )
    else:
        cur_draw.rounded_rectangle(
            [(MARGIN_X, y), (PAGE_WIDTH - MARGIN_X, y + banner_h)],
            radius=6,
            fill=BG_HEADER,
            outline=BORDER_CARD,
            width=1,
        )
        status_text = f"Differences identified: +{result.stats.added} added, -{result.stats.removed} removed, ~{result.stats.changed} modified lines."
        cur_draw.text(
            (MARGIN_X + 16, y + 8),
            status_text,
            fill=TEXT_MAIN,
            font=font_body,
        )

    y += banner_h + 24

    # Detailed Comparison Table Header helper
    col_w = (CONTENT_WIDTH - 16) // 2
    col_b_x = MARGIN_X + col_w + 16
    gutter_w = 46

    def draw_table_headers(draw: ImageDraw.ImageDraw, cur_y: int) -> int:
        th_h = 28
        # Left Table Header
        draw.rounded_rectangle(
            [(MARGIN_X, cur_y), (MARGIN_X + col_w, cur_y + th_h)],
            radius=4,
            fill=BG_HEADER,
            outline=BORDER_LIGHT,
            width=1,
        )
        draw.text((MARGIN_X + 8, cur_y + 6), "#", fill=TEXT_MUTED, font=font_caption)
        draw.text((MARGIN_X + gutter_w + 6, cur_y + 6), f"A — {left_name}", fill=TEXT_MAIN, font=font_body_bold)

        # Right Table Header
        draw.rounded_rectangle(
            [(col_b_x, cur_y), (col_b_x + col_w, cur_y + th_h)],
            radius=4,
            fill=BG_HEADER,
            outline=BORDER_LIGHT,
            width=1,
        )
        draw.text((col_b_x + 8, cur_y + 6), "#", fill=TEXT_MUTED, font=font_caption)
        draw.text((col_b_x + gutter_w + 6, cur_y + 6), f"B — {right_name}", fill=TEXT_MAIN, font=font_body_bold)
        return cur_y + th_h + 4

    y = draw_table_headers(cur_draw, y)

    # Render Rows
    row_idx = 0
    while row_idx < len(rows_to_render) and len(pages) <= max_pages:
        # Check page break
        if y + ROW_HEIGHT > BOTTOM_LIMIT:
            cur_img = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), BG_WHITE)
            cur_draw = ImageDraw.Draw(cur_img)
            pages.append(cur_img)
            y = MARGIN_Y
            # Running header on continuation pages
            cur_draw.text((MARGIN_X, y), f"DiffAnyDoc  ·  {left_name}  ↔  {right_name}", fill=TEXT_MUTED, font=font_caption)
            y += 20
            cur_draw.line([(MARGIN_X, y), (PAGE_WIDTH - MARGIN_X, y)], fill=BORDER_LIGHT, width=1)
            y += 12
            y = draw_table_headers(cur_draw, y)

        row = rows_to_render[row_idx]
        row_idx += 1

        # Check for gap
        if row.hidden_before:
            cur_draw.rectangle(
                [(MARGIN_X, y), (PAGE_WIDTH - MARGIN_X, y + 20)],
                fill=BG_CARD,
                outline=BORDER_LIGHT,
                width=1,
            )
            gap_txt = f"⋯  {row.hidden_before} lines unchanged  ⋯"
            tb_gap = cur_draw.textbbox((0, 0), gap_txt, font=font_caption)
            gx = (PAGE_WIDTH - (tb_gap[2] - tb_gap[0])) // 2
            cur_draw.text((gx, y + 3), gap_txt, fill=TEXT_MUTED, font=font_caption)
            y += 24
            if y + ROW_HEIGHT > BOTTOM_LIMIT:
                continue

        # Cell styles based on row kind
        if row.kind == "insert":
            bg_left = BG_CARD
            border_left = BORDER_LIGHT
            text_color_left = TEXT_DIM
            bg_right = DIFF_INS_BG
            border_right = DIFF_INS_BORDER
            text_color_right = DIFF_INS_TEXT
            badge_right = "+"
            badge_left = ""
        elif row.kind == "delete":
            bg_left = DIFF_DEL_BG
            border_left = DIFF_DEL_BORDER
            text_color_left = DIFF_DEL_TEXT
            bg_right = BG_CARD
            border_right = BORDER_LIGHT
            text_color_right = TEXT_DIM
            badge_left = "−"
            badge_right = ""
        elif row.kind == "replace":
            bg_left = DIFF_MOD_BG
            border_left = DIFF_MOD_BORDER
            text_color_left = DIFF_MOD_TEXT
            bg_right = DIFF_MOD_BG
            border_right = DIFF_MOD_BORDER
            text_color_right = DIFF_MOD_TEXT
            badge_left = "~"
            badge_right = "~"
        else:
            bg_left = DIFF_SAME_BG
            border_left = DIFF_SAME_BORDER
            text_color_left = TEXT_MAIN
            bg_right = DIFF_SAME_BG
            border_right = DIFF_SAME_BORDER
            text_color_right = TEXT_MAIN
            badge_left = ""
            badge_right = ""

        # Draw Left Cell
        cur_draw.rectangle(
            [(MARGIN_X, y), (MARGIN_X + col_w, y + ROW_HEIGHT - 2)],
            fill=bg_left,
            outline=border_left,
            width=1,
        )
        num_left_str = str(row.left.number) if row.left else ""
        cur_draw.text((MARGIN_X + 6, y + 4), num_left_str, fill=TEXT_MUTED, font=font_caption)
        if badge_left:
            cur_draw.text((MARGIN_X + gutter_w - 14, y + 4), badge_left, fill=text_color_left, font=font_body_bold)
        cur_draw.line(
            [(MARGIN_X + gutter_w, y), (MARGIN_X + gutter_w, y + ROW_HEIGHT - 2)],
            fill=border_left,
            width=1,
        )
        txt_left = row.left.text if row.left else ""
        txt_left_trunc = _truncate_text(cur_draw, txt_left, font_code, col_w - gutter_w - 12)
        cur_draw.text((MARGIN_X + gutter_w + 6, y + 4), txt_left_trunc, fill=text_color_left, font=font_code)

        # Draw Right Cell
        cur_draw.rectangle(
            [(col_b_x, y), (col_b_x + col_w, y + ROW_HEIGHT - 2)],
            fill=bg_right,
            outline=border_right,
            width=1,
        )
        num_right_str = str(row.right.number) if row.right else ""
        cur_draw.text((col_b_x + 6, y + 4), num_right_str, fill=TEXT_MUTED, font=font_caption)
        if badge_right:
            cur_draw.text((col_b_x + gutter_w - 14, y + 4), badge_right, fill=text_color_right, font=font_body_bold)
        cur_draw.line(
            [(col_b_x + gutter_w, y), (col_b_x + gutter_w, y + ROW_HEIGHT - 2)],
            fill=border_right,
            width=1,
        )
        txt_right = row.right.text if row.right else ""
        txt_right_trunc = _truncate_text(cur_draw, txt_right, font_code, col_w - gutter_w - 12)
        cur_draw.text((col_b_x + gutter_w + 6, y + 4), txt_right_trunc, fill=text_color_right, font=font_code)

        y += ROW_HEIGHT

    # Draw footers on all pages
    total_pages = len(pages)
    for p_idx, page in enumerate(pages):
        d = ImageDraw.Draw(page)
        fy = PAGE_HEIGHT - 45
        d.line([(MARGIN_X, fy - 10), (PAGE_WIDTH - MARGIN_X, fy - 10)], fill=BORDER_LIGHT, width=1)
        d.text((MARGIN_X, fy), "DiffAnyDoc · Confidential & Tamper-Evident Local Comparison Report", fill=TEXT_MUTED, font=font_caption)
        p_str = f"Page {p_idx + 1} of {total_pages}"
        tb_p = d.textbbox((0, 0), p_str, font=font_caption)
        d.text((PAGE_WIDTH - MARGIN_X - (tb_p[2] - tb_p[0]), fy), p_str, fill=TEXT_MUTED, font=font_caption)

    # Save all pages as multi-page PDF
    buf = io.BytesIO()
    pages[0].save(
        buf,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=150.0,
    )
    return buf.getvalue()


def write_pdf_report(
    result: DiffResult,
    path: Path | str,
    language: str | None = None,
    max_pages: int = 100,
    diff_only: bool = False,
) -> Path:
    """Render and write a PDF comparison report to the specified file path."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = render_pdf(result, language=language, max_pages=max_pages, diff_only=diff_only)
    dest.write_bytes(pdf_bytes)
    return dest
