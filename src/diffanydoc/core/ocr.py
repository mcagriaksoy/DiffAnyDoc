"""OCR fallback for pages without a text layer (scans, photos, images).

The engine is Tesseract (Apache-2.0), called as a separate program rather than
linked in: no binary wheels, no licence entanglement, and users can install
extra language packs themselves. When it is not installed the comparison still
works; the document carries an ``ocr_unavailable`` warning and the visual diff
remains available.

Results are cached on disk, keyed by the file's content hash, page, resolution,
language and engine version, so re-opening the same scan is instant.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Protocol

from .layout import make_line
from .model import BBox, Block

#: Words below this confidence (0-100) are dropped as noise.
MIN_CONFIDENCE = 30.0
CACHE_VERSION = 1


class OcrError(RuntimeError):
    pass


@dataclass(slots=True)
class OcrWord:
    text: str
    bbox: BBox  # pixels of the rendered image
    confidence: float
    line_key: tuple[int, ...]


class OcrEngine(Protocol):
    name: str

    def version(self) -> str: ...

    def languages(self) -> list[str]: ...

    def default_language(self) -> str: ...

    def recognize(self, image: Any, lang: str) -> list[OcrWord]: ...


# --------------------------------------------------------------------------- #
# Tesseract
# --------------------------------------------------------------------------- #


def _no_window() -> dict[str, Any]:
    """Do not flash a console window per page on Windows."""
    if sys.platform == "win32":  # pragma: no cover - platform specific
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def find_tesseract() -> str | None:
    explicit = os.environ.get("DIFFANYDOC_TESSERACT")
    if explicit:
        return explicit if Path(explicit).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":  # pragma: no cover - platform specific
        for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
                if candidate.is_file():
                    return str(candidate)
    return None


class TesseractEngine:
    name = "tesseract"

    #: Preferred languages when the caller does not choose: the app ships
    #: English and Turkish, so use whichever of those are installed.
    PREFERRED = ("eng", "tur")

    def __init__(self, binary: str) -> None:
        self.binary = binary

    def _run(self, args: list[str], data: bytes | None = None, timeout: float = 120) -> bytes:
        try:
            completed = subprocess.run(
                [self.binary, *args],
                input=data,
                capture_output=True,
                timeout=timeout,
                check=False,
                **_no_window(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OcrError(f"tesseract failed: {exc}") from exc
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise OcrError(f"tesseract failed: {message or completed.returncode}")
        return completed.stdout

    @lru_cache(maxsize=1)
    def version(self) -> str:
        try:
            out = self._run(["--version"], timeout=15)
        except OcrError:
            return "unknown"
        first = out.decode("utf-8", errors="replace").splitlines()
        return first[0].strip() if first else "unknown"

    @lru_cache(maxsize=1)
    def languages(self) -> list[str]:
        try:
            out = self._run(["--list-langs"], timeout=15).decode("utf-8", errors="replace")
        except OcrError:
            return []
        langs = [line.strip() for line in out.splitlines()[1:] if line.strip()]
        return [lang for lang in langs if lang != "osd"]

    def default_language(self) -> str:
        installed = self.languages()
        chosen = [lang for lang in self.PREFERRED if lang in installed]
        if chosen:
            return "+".join(chosen)
        return installed[0] if installed else "eng"

    def recognize(self, image: Any, lang: str) -> list[OcrWord]:
        buffer = io.BytesIO()
        image.convert("L").save(buffer, format="PNG")
        # --psm 3: automatic page segmentation (no OSD), the right default for
        # document pages. preserve_interword_spaces keeps column gaps visible.
        out = self._run(
            [
                "stdin",
                "stdout",
                "-l",
                lang,
                "--psm",
                "3",
                "-c",
                "preserve_interword_spaces=1",
                "tsv",
            ],
            data=buffer.getvalue(),
        )
        return parse_tsv(out.decode("utf-8", errors="replace"))


def parse_tsv(text: str) -> list[OcrWord]:
    words: list[OcrWord] = []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        try:
            if int(row.get("level") or 0) != 5:
                continue
            word = (row.get("text") or "").strip()
            confidence = float(row.get("conf") or -1)
            if not word or confidence < MIN_CONFIDENCE:
                continue
            left, top = int(row["left"]), int(row["top"])
            width, height = int(row["width"]), int(row["height"])
            key = (
                int(row.get("page_num") or 0),
                int(row.get("block_num") or 0),
                int(row.get("par_num") or 0),
                int(row.get("line_num") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
        words.append(
            OcrWord(
                text=word,
                bbox=(left, top, left + width, top + height),
                confidence=confidence,
                line_key=key,
            )
        )
    return words


# --------------------------------------------------------------------------- #
# Engine selection
# --------------------------------------------------------------------------- #

_ENGINE_OVERRIDE: list[OcrEngine | None] = []


def set_engine(engine: OcrEngine | None) -> None:
    """Install a specific engine (tests, embedding). ``None`` disables OCR."""
    _ENGINE_OVERRIDE[:] = [engine]


def reset_engine() -> None:
    _ENGINE_OVERRIDE.clear()
    _detect.cache_clear()


@lru_cache(maxsize=1)
def _detect() -> OcrEngine | None:
    if os.environ.get("DIFFANYDOC_OCR", "").lower() in ("0", "off", "false", "no"):
        return None
    binary = find_tesseract()
    return TesseractEngine(binary) if binary else None


def default_engine() -> OcrEngine | None:
    if _ENGINE_OVERRIDE:
        return _ENGINE_OVERRIDE[0]
    return _detect()


def status() -> dict[str, Any]:
    engine = default_engine()
    if engine is None:
        return {"available": False}
    return {
        "available": True,
        "engine": engine.name,
        "version": engine.version(),
        "languages": engine.languages(),
        "default_language": engine.default_language(),
    }


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


def cache_dir() -> Path:
    explicit = os.environ.get("DIFFANYDOC_CACHE_DIR")
    if explicit:
        return Path(explicit) / "ocr"
    if sys.platform == "win32":  # pragma: no cover - platform specific
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "DiffAnyDoc" / "cache" / "ocr"
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "diffanydoc" / "ocr"


@lru_cache(maxsize=64)
def _file_hash(path: str, mtime: float, size: int) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_hash(path: Path) -> str:
    stat = path.stat()
    return _file_hash(str(path), stat.st_mtime, stat.st_size)


def _cache_path(engine: OcrEngine, path: Path, index: int, dpi: int, lang: str) -> Path:
    key = "|".join(
        [str(CACHE_VERSION), engine.name, engine.version(), lang, str(dpi), str(index)]
    )
    suffix = hashlib.sha256(key.encode()).hexdigest()[:16]
    return cache_dir() / f"{file_hash(path)}-{index}-{suffix}.json"


def _read_cache(target: Path) -> list[OcrWord] | None:
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return [
            OcrWord(w["text"], tuple(w["bbox"]), w["conf"], tuple(w["line"]))  # type: ignore[arg-type]
            for w in payload["words"]
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(target: Path, words: list[OcrWord]) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "words": [
                {"text": w.text, "bbox": list(w.bbox), "conf": w.confidence, "line": list(w.line_key)}
                for w in words
            ]
        }
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        pass  # a read-only cache must not break the comparison


# --------------------------------------------------------------------------- #
# Page recognition
# --------------------------------------------------------------------------- #


def recognize_page(
    engine: OcrEngine,
    path: Path,
    index: int,
    render: Callable[[int], Any],
    *,
    page_width: float,
    page_height: float,
    dpi: int,
    lang: str,
) -> list[Block]:
    """OCR one page and return text blocks in page units, with word spans."""
    target = _cache_path(engine, path, index, dpi, lang)
    words = _read_cache(target)
    image_size: tuple[int, int] | None = None
    if words is None:
        image = render(dpi)
        image_size = image.size
        words = engine.recognize(image, lang)
        _write_cache(target, words)

    if image_size is None:
        # Cached words are in pixels at ``dpi``; recompute the scale from it.
        scale_x = scale_y = 72.0 / dpi
    else:
        scale_x = page_width / image_size[0] if page_width else 72.0 / dpi
        scale_y = page_height / image_size[1] if page_height else 72.0 / dpi
    return words_to_blocks(words, index, scale_x, scale_y)


def words_to_blocks(
    words: list[OcrWord], page_index: int, scale_x: float, scale_y: float
) -> list[Block]:
    lines: dict[tuple[int, ...], list[OcrWord]] = {}
    for word in words:
        lines.setdefault(word.line_key, []).append(word)

    ordered = sorted(
        lines.values(), key=lambda ws: (min(w.bbox[1] for w in ws), min(w.bbox[0] for w in ws))
    )
    blocks: list[Block] = []
    for group in ordered:
        group.sort(key=lambda w: w.bbox[0])
        heights = sorted(w.bbox[3] - w.bbox[1] for w in group)
        confidence = sum(w.confidence for w in group) / len(group)
        blocks.append(
            make_line(
                [
                    (
                        w.text,
                        (
                            w.bbox[0] * scale_x,
                            w.bbox[1] * scale_y,
                            w.bbox[2] * scale_x,
                            w.bbox[3] * scale_y,
                        ),
                    )
                    for w in group
                ],
                page_index,
                style={
                    "ocr": True,
                    "confidence": round(confidence, 1),
                    # Cap height ≈ 0.7 × font size; good enough for reflow.
                    "size": round(heights[len(heights) // 2] * scale_y / 0.72, 1),
                },
                source_ref={"line": len(blocks)},
            )
        )
    return blocks
