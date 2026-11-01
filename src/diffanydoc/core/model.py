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

BBox = tuple[float, float, float, float]  # x0, top, x1, bottom (points)


# --------------------------------------------------------------------------- #
# Document IR
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Block:
    """A single addressable unit of content, e.g. one text line."""

    kind: BlockKind = "text"
    text: str = ""
    bbox: BBox | None = None
    style: dict[str, Any] = field(default_factory=dict)
    children: list["Block"] = field(default_factory=list)
    source_ref: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Page:
    index: int
    width: float = 0.0
    height: float = 0.0
    blocks: list[Block] = field(default_factory=list)

    def text(self, sep: str = "\n") -> str:
        return sep.join(b.text for b in self.blocks if b.kind == "text")


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


@dataclass(slots=True)
class PagePair:
    """Result of page alignment: which page corresponds to which."""

    left: int | None
    right: int | None
    similarity: float


@dataclass(slots=True)
class Stats:
    left_lines: int = 0
    right_lines: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    similarity: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "left_lines": self.left_lines,
            "right_lines": self.right_lines,
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "similarity": round(self.similarity, 4),
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
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def identical(self) -> bool:
        return not any(r.kind != "equal" for r in self.rows)

    @property
    def change_count(self) -> int:
        return sum(1 for r in self.rows if r.kind != "equal")
