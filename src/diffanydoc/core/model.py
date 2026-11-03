"""The document model (IR) and the diff result model.

Every supported format is reduced to this IR, so the comparison engine only
ever deals with one shape of data. Adding a format means adding one adapter,
not one comparison algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

BlockKind = Literal["text", "table", "image", "vector"]
ChangeKind = Literal["equal", "insert", "delete", "replace"]

BBox = tuple[float, float, float, float]  # x0, top, x1, bottom (page units)


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
    """A single addressable unit of content, e.g. one text line or table row."""

    kind: BlockKind = "text"
    text: str = ""
    bbox: BBox | None = None
    style: dict[str, Any] = field(default_factory=dict)
    children: list["Block"] = field(default_factory=list)
    source_ref: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    #: Table rows: one string per cell. ``text`` is the cells joined by " | ".
    cells: list[str] | None = None
    #: Short location label shown in the gutter, e.g. a spreadsheet row number.
    label: str | None = None


@dataclass(slots=True)
class Page:
    index: int
    width: float = 0.0
    height: float = 0.0
    blocks: list[Block] = field(default_factory=list)
    #: Human name for pages that are not numbered pages: sheet names,
    #: "Headers & footers", "Footnotes"... Also used to match pages by name.
    label: str | None = None
    #: How the text was obtained: "text" (text layer), "ocr" or "none".
    source: str = "text"

    def text(self, sep: str = "\n") -> str:
        return sep.join(b.text for b in self.blocks if b.kind == "text")


@dataclass(slots=True)
class Document:
    path: Path
    kind: str
    pages: list[Page] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    #: Notes for the user, e.g. ``{"code": "ocr_used", "pages": [1, 2]}``.
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def text(self, sep: str = "\n") -> str:
        return sep.join(p.text(sep) for p in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(p.text("")) for p in self.pages)

    @property
    def renderable(self) -> bool:
        """True when pages can be drawn as images (PDF pages, images)."""
        return self.kind in ("pdf", "image")


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
    spans: list[Span] = field(default_factory=list)
    cells: list[str] | None = None
    label: str | None = None


@dataclass(slots=True)
class Segment:
    """Inline change inside a paired (replace) line."""

    kind: Literal["equal", "insert", "delete"]
    text: str


@dataclass(slots=True)
class CellDiff:
    """One aligned cell of a changed table row."""

    kind: ChangeKind
    left: str | None = None
    right: str | None = None
    left_inline: list[Segment] | None = None
    right_inline: list[Segment] | None = None
    #: Column label when the format has one (spreadsheet "C").
    left_column: str | None = None
    right_column: str | None = None


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
    #: Table rows that were paired: the cell-by-cell alignment.
    cells: list[CellDiff] | None = None
    #: Equal text but different formatting, e.g. ``["bold", "heading"]``.
    format_changes: list[str] | None = None


@dataclass(slots=True)
class PagePair:
    """Result of page alignment: which page corresponds to which."""

    left: int | None
    right: int | None
    similarity: float


@dataclass(slots=True)
class VisualRegion:
    """A changed area found by the pixel comparison, in page units."""

    x0: float
    top: float
    x1: float
    bottom: float
    #: "delete" (ink only on the left), "insert" (only on the right), "replace".
    kind: str
    #: Changed pixels inside the region, as a share of the region area.
    density: float = 0.0


@dataclass(slots=True)
class VisualPage:
    """Pixel comparison of one aligned page pair."""

    pair: int
    left: int | None
    right: int | None
    #: Share of inked pixels that changed (0..1).
    changed_ratio: float = 0.0
    regions: list[VisualRegion] = field(default_factory=list)
    #: Registration offset applied to the right page, in page units.
    offset: tuple[float, float] = (0.0, 0.0)
    #: Page sizes differ, the right page was scaled to the left page.
    scaled: bool = False

    @property
    def identical(self) -> bool:
        return not self.regions


@dataclass(slots=True)
class Stats:
    left_lines: int = 0
    right_lines: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    similarity: float = 0.0
    #: Equal text, different formatting (only when formatting is compared).
    formatting: int = 0
    #: Changed regions found by the visual comparison (when it ran).
    visual_regions: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "left_lines": self.left_lines,
            "right_lines": self.right_lines,
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "formatting": self.formatting,
            "visual_regions": self.visual_regions,
            "similarity": round(self.similarity, 4),
        }


@dataclass(slots=True)
class DocumentInfo:
    """What the result needs to know about each input after loading."""

    path: Path
    kind: str
    pages: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    sha256: str = ""
    renderable: bool = False

    @classmethod
    def of(cls, document: Document, sha256: str = "") -> "DocumentInfo":
        return cls(
            path=document.path,
            kind=document.kind,
            pages=[
                {
                    "width": page.width,
                    "height": page.height,
                    "label": page.label,
                    "source": page.source,
                }
                for page in document.pages
            ],
            meta=dict(document.meta),
            warnings=list(document.warnings),
            sha256=sha256,
            renderable=document.renderable,
        )


@dataclass(slots=True)
class DiffResult:
    left_path: Path
    right_path: Path
    left_kind: str
    right_kind: str
    rows: list[Row] = field(default_factory=list)
    page_map: list[PagePair] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)
    options: dict[str, Any] = field(default_factory=dict)
    left_info: DocumentInfo | None = None
    right_info: DocumentInfo | None = None
    #: The two files have the same bytes; nothing else was compared.
    byte_identical: bool = False
    #: ``None`` when the visual comparison did not run.
    visual: list[VisualPage] | None = None

    @property
    def text_identical(self) -> bool:
        return not any(r.kind != "equal" or r.format_changes for r in self.rows)

    @property
    def identical(self) -> bool:
        if self.byte_identical:
            return True
        if not self.text_identical:
            return False
        if self.visual is not None and any(not page.identical for page in self.visual):
            return False
        return True

    @property
    def change_count(self) -> int:
        return sum(1 for r in self.rows if r.kind != "equal" or r.format_changes)
