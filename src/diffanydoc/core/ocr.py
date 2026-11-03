"""OCR fallback for PDF pages without a text layer.

Scanned PDFs carry an image, not text. This module renders such pages, runs
Tesseract (Apache-2.0) through its command line, and turns the recognised
words into ordinary text blocks with bounding boxes. The rest of the pipeline
— line alignment, inline diff, page rectangles — works unchanged.

Results are cached on disk by file content hash, page, language and options,
so comparing the same scan twice is cheap. Tesseract is an optional system
dependency; everything else in DiffAnyDoc works without it.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import Block, BBox, Document, OcrStats, Page
from .normalize import normalize_line
from .render import render_page

#: Bump when the cache payload changes shape.
_CACHE_VERSION = 1

#: Fallback languages offered in the UI when Tesseract is not probed or has more.
_DEFAULT_LANGUAGES = ("eng", "tur", "tur+eng")

#: Options passed to Tesseract's TSV output; columns we care about.
_TSV_COLUMNS = (
    "level",
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
)

_INSTALL_HINT = (
    "tesseract is required for OCR. Install it (Debian/Ubuntu: "
    "sudo apt install tesseract-ocr tesseract-ocr-eng) or set "
    "DIFFANYDOC_TESSERACT to the binary path."
)


class OcrError(RuntimeError):
    """OCR was requested but could not be completed."""


class OcrUnavailable(OcrError):
    """No Tesseract binary is installed or configured."""


@dataclass(slots=True)
class OcrOptions:
    """Tuning knobs for the OCR fallback layer."""

    #: Tesseract language(s), e.g. ``eng`` or ``tur+eng``.
    language: str = "eng"
    #: Rendering resolution. 300 dpi is the usual sweet spot for scans.
    dpi: int = 300
    #: Tesseract page segmentation mode. 3 = fully automatic.
    psm: int = 3
    #: A page with fewer non-whitespace characters than this is treated as
    #: scanned. Small enough to catch a page number, large enough to skip it.
    min_text_chars: int = 8
    #: Safety valve for very long scans; the rest is reported as truncated.
    max_pages: int = 60
    #: Per-page Tesseract timeout in seconds.
    timeout: float = 120.0
    #: Cache root; ``None`` uses the per-user cache directory.
    cache_dir: Path | str | None = None
    #: Explicit binary path; ``None`` searches ``PATH`` and the env override.
    binary: str | None = None


def _needs_ocr(page: Page, options: OcrOptions) -> bool:
    """Whether a page needs OCR (sparse text layer or embedded raster scan)."""
    length = _text_length(page)
    if length < max(options.min_text_chars, 0):
        return True
    has_image = any(block.kind == "image" for block in page.blocks)
    if has_image and length < max(options.min_text_chars * 10, 80):
        return True
    return False


def _merge_ocr_blocks(page: Page, ocr_blocks: list[Block]) -> int:
    """Append OCR blocks that do not duplicate already-extracted text lines."""
    existing_norms = {
        normalize_line(b.text, case_sensitive=False)
        for b in page.blocks
        if b.kind == "text" and b.text.strip()
    }
    existing_boxes = [
        b.bbox for b in page.blocks if b.kind == "text" and b.bbox is not None
    ]
    added_words = 0
    for block in ocr_blocks:
        norm = normalize_line(block.text, case_sensitive=False)
        if not norm or norm in existing_norms:
            continue
        if block.bbox is not None and any(
            _boxes_overlap(block.bbox, box) for box in existing_boxes
        ):
            continue
        page.blocks.append(block)
        existing_norms.add(norm)
        added_words += len(block.text.split())
    return added_words


def _boxes_overlap(a: BBox, b: BBox) -> bool:
    """Whether two bounding boxes share significant vertical and horizontal overlap."""
    v_top = max(a[1], b[1])
    v_bot = min(a[3], b[3])
    if v_bot - v_top <= 0:
        return False
    h_left = max(a[0], b[0])
    h_right = min(a[2], b[2])
    return h_right - h_left > 4.0


def apply_ocr(
    document: Document, options: OcrOptions | None = None
) -> OcrStats | None:
    """OCR the pages of ``document`` that have no usable text layer.

    Blocks are appended to the page in place. Returns ``None`` when nothing
    needed OCR, so a normal text PDF never requires Tesseract.
    """
    options = options or OcrOptions()
    if document.kind not in ("pdf", "image"):
        return None

    pages = [page for page in document.pages if _needs_ocr(page, options)]
    if not pages:
        return None

    binary: str | None = None
    use_rapidocr = False
    try:
        binary = _tesseract_binary(options)
    except OcrUnavailable:
        if _rapidocr_available():
            use_rapidocr = True
        else:
            raise
    if (
        binary is not None
        and options.binary is None
        and not os.environ.get("DIFFANYDOC_TESSERACT")
        and _tesseract_binary is _DEFAULT_TESSERACT_BINARY
        and _rapidocr_available()
    ):
        use_rapidocr = True
    cache = _OcrCache(options.cache_dir)
    digest = _file_digest(Path(document.path))
    stats = OcrStats(language=options.language)
    limit = max(options.max_pages, 0)
    stats.truncated = len(pages) > limit

    for page in pages[:limit]:
        cached = cache.get(digest, page, options)
        if cached is not None:
            blocks = [_block_from_dict(item) for item in cached]
            stats.cached += 1
        else:
            image = render_page(document.path, page.index, options.dpi)
            if page.width <= 0 or page.height <= 0:
                page.width = image.width * 72.0 / options.dpi
                page.height = image.height * 72.0 / options.dpi
            if use_rapidocr:
                blocks = _run_rapidocr(image, options.dpi)
            else:
                assert binary is not None
                blocks = _run_tesseract(_png_bytes(image), options, binary)
            cache.put(
                digest,
                page,
                options,
                [_block_to_dict(block) for block in blocks],
            )

        words = _merge_ocr_blocks(page, blocks)
        stats.pages += 1
        stats.words += words

    document.meta["ocr"] = stats.as_dict()
    return stats


def available(options: OcrOptions | None = None) -> bool:
    """Whether an OCR engine (RapidOCR or Tesseract) is available."""
    if _rapidocr_available():
        return True
    try:
        _tesseract_binary(options or OcrOptions())
    except OcrUnavailable:
        return False
    return True


_RAPIDOCR_INSTANCE: Any = None


def _rapidocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except ImportError:
        return False


def _get_rapidocr() -> Any:
    global _RAPIDOCR_INSTANCE
    if _RAPIDOCR_INSTANCE is None:
        from rapidocr_onnxruntime import RapidOCR

        _RAPIDOCR_INSTANCE = RapidOCR()
    return _RAPIDOCR_INSTANCE


def _run_rapidocr(image: Any, dpi: int) -> list[Block]:
    """Run embedded RapidOCR (Apache-2.0, ONNX Runtime) on a rendered PIL image."""
    try:
        engine = _get_rapidocr()
        rgb = image.convert("RGB")
        result, _elapse = engine(rgb)
    except Exception as exc:
        raise OcrError(f"RapidOCR failed: {exc}") from exc

    if not result:
        return []

    scale = 72.0 / max(dpi, 1)
    raw_items: list[dict[str, Any]] = []
    for entry in result:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        quad, text_raw, score_raw = entry[0], entry[1], entry[2]
        text = str(text_raw or "").strip()
        if not text:
            continue
        try:
            xs = [float(pt[0]) for pt in quad]
            ys = [float(pt[1]) for pt in quad]
            left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
            confidence = float(score_raw) * 100.0 if float(score_raw) <= 1.0 else float(score_raw)
        except (TypeError, ValueError, IndexError):
            continue
        raw_items.append(
            {
                "text": text,
                "left": left * scale,
                "top": top * scale,
                "right": right * scale,
                "bottom": bottom * scale,
                "confidence": confidence,
            }
        )

    if not raw_items:
        return []

    # Sort top-to-bottom, then left-to-right, and merge boxes on the same visual line
    raw_items.sort(key=lambda item: (round(item["top"] / 4.0), item["left"]))
    merged_lines: list[dict[str, Any]] = []
    for item in raw_items:
        if merged_lines:
            prev = merged_lines[-1]
            prev_h = max(prev["bottom"] - prev["top"], 4.0)
            if abs(item["top"] - prev["top"]) <= prev_h * 0.55:
                prev["words"].append(item)
                prev["left"] = min(prev["left"], item["left"])
                prev["top"] = min(prev["top"], item["top"])
                prev["right"] = max(prev["right"], item["right"])
                prev["bottom"] = max(prev["bottom"], item["bottom"])
                continue
        merged_lines.append(
            {
                "words": [item],
                "left": item["left"],
                "top": item["top"],
                "right": item["right"],
                "bottom": item["bottom"],
            }
        )

    lines_out: list[dict[str, Any]] = []
    for line in merged_lines:
        words = sorted(line["words"], key=lambda w: w["left"])
        avg_conf = sum(w["confidence"] for w in words) / len(words)
        lines_out.append(
            {
                "text": " ".join(w["text"] for w in words),
                "bbox": (
                    round(line["left"], 2),
                    round(line["top"], 2),
                    round(line["right"], 2),
                    round(line["bottom"], 2),
                ),
                "confidence": round(avg_conf, 1),
            }
        )
    return _words_to_blocks(lines_out)


def installed_languages(options: OcrOptions | None = None) -> list[str]:
    """Return Tesseract language codes installed on the system, plus combos."""
    try:
        binary = _tesseract_binary(options or OcrOptions())
        completed = subprocess.run(
            [binary, "--list-langs"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5.0,
            check=False,
        )
    except (OcrUnavailable, OSError, subprocess.SubprocessError):
        return list(_DEFAULT_LANGUAGES)

    raw = (
        completed.stdout.decode("utf-8", "replace")
        + "\n"
        + completed.stderr.decode("utf-8", "replace")
    )
    codes: list[str] = []
    for line in raw.splitlines():
        token = line.strip()
        if not token or " " in token or ":" in token or token == "osd":
            continue
        if re.fullmatch(r"[a-z]{3}(?:_[a-z]+)?", token) and token not in codes:
            codes.append(token)
    if not codes:
        return list(_DEFAULT_LANGUAGES)
    if "tur" in codes and "eng" in codes and "tur+eng" not in codes:
        codes.append("tur+eng")
    return codes


def default_cache_dir() -> Path:
    """Per-user cache directory, overridable with ``DIFFANYDOC_CACHE_DIR``."""
    override = os.environ.get("DIFFANYDOC_CACHE_DIR")
    if override:
        return Path(override).expanduser() / "ocr"
    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        )
        return base / "DiffAnyDoc" / "cache" / "ocr"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "DiffAnyDoc" / "ocr"
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "diffanydoc" / "ocr"


def clear_cache(options: OcrOptions | None = None) -> int:
    """Remove cached OCR pages; returns the number of files deleted."""
    root = _OcrCache((options or OcrOptions()).cache_dir).root
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.rglob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:  # pragma: no cover - permissions / races
            continue
    return removed


# --------------------------------------------------------------------------- #
# Tesseract
# --------------------------------------------------------------------------- #


def _tesseract_binary(options: OcrOptions) -> str:
    candidates = [
        options.binary,
        os.environ.get("DIFFANYDOC_TESSERACT"),
        shutil.which("tesseract"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    raise OcrUnavailable(_INSTALL_HINT)


_DEFAULT_TESSERACT_BINARY = _tesseract_binary


def _png_bytes(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.convert("L").save(buffer, format="PNG")
    return buffer.getvalue()


def _run_tesseract(
    png: bytes, options: OcrOptions, binary: str
) -> list[Block]:
    command = [
        binary,
        "stdin",
        "stdout",
        "-l",
        options.language,
        "--psm",
        str(options.psm),
        "tsv",
    ]
    try:
        completed = subprocess.run(
            command,
            input=png,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(options.timeout, 1.0),
            check=False,
        )
    except FileNotFoundError as exc:
        raise OcrUnavailable(_INSTALL_HINT) from exc
    except subprocess.TimeoutExpired as exc:
        raise OcrError(
            f"tesseract timed out after {options.timeout:g}s on page OCR"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        message = detail[-1] if detail else f"exit code {completed.returncode}"
        raise OcrError(f"tesseract failed: {message}")

    tsv = completed.stdout.decode("utf-8", "replace")
    words = _parse_tsv(tsv, options.dpi)
    return _words_to_blocks(words)


def _parse_tsv(tsv: str, dpi: int) -> list[dict[str, Any]]:
    """Group word-level TSV rows into lines with PDF-point bounding boxes."""
    lines = tsv.splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    try:
        index = {name: header.index(name) for name in _TSV_COLUMNS}
    except ValueError:
        return []

    scale = 72.0 / max(dpi, 1)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for raw in lines[1:]:
        columns = raw.split("\t")
        if len(columns) <= index["text"] or columns[index["level"]] != "5":
            continue
        text = columns[index["text"]].strip()
        if not text:
            continue
        try:
            confidence = float(columns[index["conf"]])
            left = float(columns[index["left"]])
            top = float(columns[index["top"]])
            width = float(columns[index["width"]])
            height = float(columns[index["height"]])
        except ValueError:
            continue
        if confidence < 0:
            continue
        key = (
            columns[index["block_num"]],
            columns[index["par_num"]],
            columns[index["line_num"]],
        )
        groups.setdefault(key, []).append(
            {
                "text": text,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "confidence": confidence,
            }
        )

    lines_out: list[dict[str, Any]] = []
    for words in groups.values():
        words.sort(key=lambda word: word["left"])
        left = min(word["left"] for word in words)
        top = min(word["top"] for word in words)
        right = max(word["left"] + word["width"] for word in words)
        bottom = max(word["top"] + word["height"] for word in words)
        confidence = sum(word["confidence"] for word in words) / len(words)
        lines_out.append(
            {
                "text": " ".join(word["text"] for word in words),
                "bbox": (
                    round(left * scale, 2),
                    round(top * scale, 2),
                    round(right * scale, 2),
                    round(bottom * scale, 2),
                ),
                "confidence": round(confidence, 1),
            }
        )
    return lines_out


def _words_to_blocks(lines: list[dict[str, Any]]) -> list[Block]:
    return [
        Block(
            kind="text",
            text=str(item["text"]),
            bbox=tuple(item["bbox"]),  # type: ignore[arg-type]
            style={"ocr": True, "confidence": item["confidence"]},
            source_ref={"ocr": True, "line": index},
        )
        for index, item in enumerate(lines)
        if str(item.get("text", "")).strip()
    ]


# --------------------------------------------------------------------------- #
# Cache and helpers
# --------------------------------------------------------------------------- #


def _text_length(page: Page) -> int:
    return len("".join(page.text().split()))


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_language(language: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", language).strip("-") or "eng"


class _OcrCache:
    """Content-addressed JSON cache for OCR page results."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root).expanduser() if root else default_cache_dir()

    def path_for(self, digest: str, page: Page, options: OcrOptions) -> Path:
        name = (
            f"{digest}-p{page.index}-{_safe_language(options.language)}"
            f"-{options.dpi}-{options.psm}-v{_CACHE_VERSION}.json"
        )
        return self.root / digest[:2] / name

    def get(
        self, digest: str, page: Page, options: OcrOptions
    ) -> list[dict[str, Any]] | None:
        path = self.path_for(digest, page, options)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("version") != _CACHE_VERSION:
            return None
        blocks = payload.get("blocks")
        if not isinstance(blocks, list):
            return None
        return [item for item in blocks if isinstance(item, dict)]

    def put(
        self,
        digest: str,
        page: Page,
        options: OcrOptions,
        blocks: list[dict[str, Any]],
    ) -> None:
        path = self.path_for(digest, page, options)
        payload = {
            "version": _CACHE_VERSION,
            "page": page.index,
            "language": options.language,
            "dpi": options.dpi,
            "psm": options.psm,
            "blocks": blocks,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=path.name + ".",
                suffix=".tmp",
                delete=False,
            )
            try:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.replace(handle.name, path)
        except OSError:  # caching must never break a comparison
            return


def _block_to_dict(block: Block) -> dict[str, Any]:
    return {
        "text": block.text,
        "bbox": list(block.bbox) if block.bbox else None,
        "confidence": block.style.get("confidence"),
    }


def _block_from_dict(item: dict[str, Any]) -> Block:
    bbox = item.get("bbox")
    return Block(
        kind="text",
        text=str(item.get("text") or ""),
        bbox=tuple(bbox) if isinstance(bbox, list) and len(bbox) == 4 else None,  # type: ignore[arg-type]
        style={"ocr": True, "confidence": item.get("confidence")},
        source_ref={"ocr": True},
    )
