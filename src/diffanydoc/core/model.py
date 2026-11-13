"""The document model (IR) and the diff result model.

Every supported format is reduced to this IR, so the comparison engine only
ever deals with one shape of data. Adding a format means adding one adapter,
not one comparison algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

BlockKind = Literal["text", "table", "table_row", "cell", "image", "vector"]
ChangeKind = Literal["equal", "insert", "delete", "replace"]

BBox = tuple[float, float, float, float]  # x0, top, x1, bottom (points)


# --------------------------------------------------------------------------- #
# Document IR
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Span:
    """Where a piece of a block's text sits on the page.

    ``start``/``end`` are character offsets into :attr:`Block.text`. Adapters
    with geometry (PDF, OCR) emit one span per word, which is what lets the
    viewer box the exact changed word instead of the whole line.
    """

    start: int
    end: int
    page: int
    bbox: BBox


@dataclass(slots=True)
class Block:
    """A single addressable unit of content, e.g. one text line."""

    kind: BlockKind = "text"
    text: str = ""
    bbox: BBox | None = None
    style: dict[str, Any] = field(default_factory=dict)
    children: list["Block"] = field(default_factory=list)
    source_ref: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    cells: list[str] | None = None
    label: str | None = None


@dataclass(slots=True)
class Page:
    index: int
    width: float = 0.0
    height: float = 0.0
    blocks: list[Block] = field(default_factory=list)
    label: str | None = None

    def text(self, sep: str = "\n") -> str:
        return sep.join(
            b.text for b in self.blocks if b.kind in ("text", "table")
        )


@dataclass(slots=True)
class Document:
    path: Path
    kind: str
    pages: list[Page] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def text(self, sep: str = "\n") -> str:
        return sep.join(p.text(sep) for p in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(p.text("")) for p in self.pages)


# --------------------------------------------------------------------------- #
# Diff result
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Line:
    """A display line: the unit the user sees and scrolls through."""

    text: str
    norm: str
    page: int
    #: 1-based line number inside its own document.
    number: int = 0
    bbox: BBox | None = None
    style: dict[str, Any] = field(default_factory=dict)
    #: Cell texts when the line comes from a table row, so changed cells can
    #: be aligned and highlighted individually instead of as one long string.
    cells: list[str] | None = None
    spans: list[Span] = field(default_factory=list)
    label: str | None = None


@dataclass(slots=True)
class Segment:
    """Inline change inside a paired (replace) line."""

    kind: Literal["equal", "insert", "delete"]
    text: str


@dataclass(slots=True)
class Row:
    """One visual row of a side-by-side comparison."""

    kind: ChangeKind
    left: Line | None = None
    right: Line | None = None
    left_inline: list[Segment] | None = None
    right_inline: list[Segment] | None = None
    #: Number of identical rows folded away before this row (0 = nothing hidden).
    hidden_before: int = 0
    format_changes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PagePair:
    """Result of page alignment: which page corresponds to which."""

    left: int | None
    right: int | None
    similarity: float


@dataclass(slots=True)
class VisualPage:
    """Pixel comparison of one aligned page pair.

    Regions are in PDF points relative to their own page, so the viewer can
    overlay them without knowing the rendering DPI.
    """

    left: int
    right: int
    shift: tuple[float, float] = (0.0, 0.0)
    changed_pixels: int = 0
    total_pixels: int = 0
    left_regions: list[BBox] = field(default_factory=list)
    right_regions: list[BBox] = field(default_factory=list)
    error: str | None = None

    @property
    def changed_ratio(self) -> float:
        return self.changed_pixels / self.total_pixels if self.total_pixels else 0.0

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "left": self.left,
            "right": self.right,
            "shift": [round(self.shift[0], 3), round(self.shift[1], 3)],
            "changed_ratio": round(self.changed_ratio, 6),
            "left_regions": _regions_as_lists(self.left_regions),
            "right_regions": _regions_as_lists(self.right_regions),
        }
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass(slots=True)
class VisualDiff:
    """Result of rendering both documents and comparing pixels page by page."""

    pages: list[VisualPage] = field(default_factory=list)
    compared: int = 0
    changed_pages: int = 0
    changed_pixels: int = 0
    total_pixels: int = 0
    max_shift: float = 0.0
    truncated: bool = False

    @property
    def similarity(self) -> float:
        if not self.total_pixels:
            return 1.0
        return max(0.0, 1.0 - self.changed_pixels / self.total_pixels)

    @property
    def region_count(self) -> int:
        return sum(
            max(len(page.left_regions), len(page.right_regions))
            for page in self.pages
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": True,
            "stats": {
                "compared": self.compared,
                "changed_pages": self.changed_pages,
                "changed_pixels": self.changed_pixels,
                "total_pixels": self.total_pixels,
                "similarity": round(self.similarity, 4),
                "max_shift": round(self.max_shift, 3),
                "regions": self.region_count,
                "truncated": self.truncated,
            },
            "pages": [page.as_dict() for page in self.pages],
        }


def _regions_as_lists(regions: list[BBox]) -> list[list[float]]:
    return [[round(value, 2) for value in region] for region in regions]


@dataclass(slots=True)
class OcrStats:
    """What the OCR fallback layer did for one comparison."""

    language: str = "eng"
    #: Pages that had little or no text and were OCRed (both documents).
    pages: int = 0
    #: How many of those pages came from the on-disk cache.
    cached: int = 0
    words: int = 0
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": True,
            "language": self.language,
            "pages": self.pages,
            "cached": self.cached,
            "words": self.words,
            "truncated": self.truncated,
        }

    def merged(self, other: "OcrStats") -> "OcrStats":
        return OcrStats(
            language=self.language,
            pages=self.pages + other.pages,
            cached=self.cached + other.cached,
            words=self.words + other.words,
            truncated=self.truncated or other.truncated,
        )


@dataclass(slots=True)
class Stats:
    left_lines: int = 0
    right_lines: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    similarity: float = 0.0
    left_words: int = 0
    right_words: int = 0
    left_chars: int = 0
    right_chars: int = 0
    left_reading_time_min: float = 0.0
    right_reading_time_min: float = 0.0
    words_added: int = 0
    words_removed: int = 0
    words_changed: int = 0
    change_density: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "left_lines": self.left_lines,
            "right_lines": self.right_lines,
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "similarity": round(self.similarity, 4),
            "left_words": self.left_words,
            "right_words": self.right_words,
            "left_chars": self.left_chars,
            "right_chars": self.right_chars,
            "left_reading_time_min": round(self.left_reading_time_min, 1),
            "right_reading_time_min": round(self.right_reading_time_min, 1),
            "words_added": self.words_added,
            "words_removed": self.words_removed,
            "words_changed": self.words_changed,
            "change_density": round(self.change_density, 4),
        }


@dataclass(slots=True)
class DiffResult:
    left_path: Path
    right_path: Path
    left_kind: str
    right_kind: str
    rows: list[Row] = field(default_factory=list)
    page_map: list[PagePair] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)
    visual: VisualDiff | None = None
    ocr: OcrStats | None = None
    options: dict[str, Any] = field(default_factory=dict)
    byte_identical: bool = False
    left_sha256: str | None = None
    right_sha256: str | None = None
    left_pages: list[tuple[float, float]] = field(default_factory=list)
    right_pages: list[tuple[float, float]] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        if self.byte_identical:
            return True
        if self.visual is not None and self.visual.changed_pages > 0:
            return False
        return not any(r.kind != "equal" for r in self.rows)

    @property
    def change_count(self) -> int:
        return sum(1 for r in self.rows if r.kind != "equal")
