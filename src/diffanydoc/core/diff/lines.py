"""Turn a document into display lines, and compare two lines' contents."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from ..layout import reflow as reflow_blocks
from ..model import CellDiff, Document, Line, Segment
from ..normalize import normalize_line

_WORD = re.compile(r"\S+|\s+")
_TOKEN = re.compile(r"\S+")
CELL_SEPARATOR = " | "


def document_lines(
    document: Document,
    *,
    case_sensitive: bool = True,
    collapse_whitespace: bool = True,
    reflow: bool = True,
) -> list[Line]:
    """Flatten all text blocks into a single sequence of comparable lines.

    Page order is preserved and each line keeps its page index, bbox and word
    spans, which is what lets the viewer jump from a diff straight to the
    position on the page. With ``reflow`` the visual lines of a paragraph are
    joined first (only for blocks with geometry: PDF and OCR text).
    """

    def norm(text: str) -> str:
        return normalize_line(
            text, case_sensitive=case_sensitive, collapse_whitespace=collapse_whitespace
        )

    lines: list[Line] = []
    for page in document.pages:
        blocks = page.blocks
        if reflow and any(b.bbox is not None for b in blocks):
            blocks = reflow_blocks(blocks, page.width)
        for block in blocks:
            if block.kind != "text":
                continue
            if block.cells is not None:
                key = CELL_SEPARATOR.join(norm(cell) for cell in block.cells)
            else:
                key = norm(block.text)
            if not key.strip(" |"):
                continue
            lines.append(
                Line(
                    text=block.text,
                    norm=key,
                    page=page.index,
                    number=len(lines) + 1,
                    bbox=block.bbox,
                    style=block.style,
                    spans=block.spans,
                    cells=block.cells,
                    label=block.label,
                )
            )
    return lines


def line_similarity(a: Line, b: Line) -> float:
    """0..1 similarity between two lines, used to pair changed rows.

    Table rows are scored mostly on how many *cells* agree: separators and
    digits make any two rows of a numeric table look alike character-wise,
    which would pair an inserted row with an unrelated one.
    """
    chars = SequenceMatcher(None, a.norm, b.norm, autojunk=False).ratio()
    if a.cells is None or b.cells is None:
        return chars
    left = a.norm.split(CELL_SEPARATOR)
    right = b.norm.split(CELL_SEPARATOR)
    cells = SequenceMatcher(None, left, right, autojunk=False).ratio()
    # The first cell is usually the row's key (item, name, id).
    key = 1.0 if left[:1] == right[:1] and left[:1] != [""] else 0.0
    return 0.5 * cells + 0.2 * key + 0.3 * chars


def _push(target: list[Segment], kind: str, text: str) -> None:
    if not text:
        return
    if target and target[-1].kind == kind:
        target[-1].text += text
    else:
        target.append(Segment(kind=kind, text=text))  # type: ignore[arg-type]


def inline_diff(
    left: str,
    right: str,
    *,
    case_sensitive: bool = True,
) -> tuple[list[Segment], list[Segment]]:
    """Word-level diff inside a pair of changed lines.

    Whitespace is kept as its own token so the reconstructed text is exact;
    tokens are compared in their normalised form, so a curly quote or a
    non-breaking space is not highlighted as a change.
    """
    a_tokens = _WORD.findall(left)
    b_tokens = _WORD.findall(right)

    def key(token: str) -> str:
        if token.isspace():
            return " "
        return normalize_line(token, case_sensitive=case_sensitive)

    matcher = SequenceMatcher(
        None, [key(t) for t in a_tokens], [key(t) for t in b_tokens], autojunk=False
    )

    left_segments: list[Segment] = []
    right_segments: list[Segment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            _push(left_segments, "equal", "".join(a_tokens[i1:i2]))
            _push(right_segments, "equal", "".join(b_tokens[j1:j2]))
        else:
            _push(left_segments, "delete", "".join(a_tokens[i1:i2]))
            _push(right_segments, "insert", "".join(b_tokens[j1:j2]))
    return left_segments, right_segments


# --------------------------------------------------------------------------- #
# Table rows
# --------------------------------------------------------------------------- #


def _column(line: Line, index: int) -> str | None:
    columns = line.style.get("columns") if line.style else None
    if columns and index < len(columns):
        return str(columns[index])
    return None


def cell_diff(
    left: Line,
    right: Line,
    *,
    case_sensitive: bool = True,
    collapse_whitespace: bool = True,
) -> list[CellDiff]:
    """Align the cells of two table rows and diff each pair of cells.

    Cells are aligned by content (LCS), not only by position, so an inserted
    column shows as one inserted cell instead of every following cell
    changing.
    """
    a = left.cells or []
    b = right.cells or []

    def norm(text: str) -> str:
        return normalize_line(
            text, case_sensitive=case_sensitive, collapse_whitespace=collapse_whitespace
        )

    matcher = SequenceMatcher(None, [norm(c) for c in a], [norm(c) for c in b], autojunk=False)
    out: list[CellDiff] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                out.append(
                    CellDiff(
                        kind="equal",
                        left=a[i],
                        right=b[j],
                        left_column=_column(left, i),
                        right_column=_column(right, j),
                    )
                )
            continue
        pairs = min(i2 - i1, j2 - j1)
        for offset in range(pairs):
            i, j = i1 + offset, j1 + offset
            li, ri = inline_diff(a[i], b[j], case_sensitive=case_sensitive)
            out.append(
                CellDiff(
                    kind="replace",
                    left=a[i],
                    right=b[j],
                    left_inline=li,
                    right_inline=ri,
                    left_column=_column(left, i),
                    right_column=_column(right, j),
                )
            )
        for i in range(i1 + pairs, i2):
            out.append(CellDiff(kind="delete", left=a[i], left_column=_column(left, i)))
        for j in range(j1 + pairs, j2):
            out.append(CellDiff(kind="insert", right=b[j], right_column=_column(right, j)))
    return out


def cells_to_inline(cells: list[CellDiff]) -> tuple[list[Segment], list[Segment]]:
    """Row-level inline segments built from the cell alignment.

    Joining the segments reproduces each side's ``text`` exactly (cells joined
    with :data:`CELL_SEPARATOR`), so consumers that only know about inline
    segments keep working.
    """
    left: list[Segment] = []
    right: list[Segment] = []
    left_seen = right_seen = False
    for cell in cells:
        if cell.left is not None:
            if left_seen:
                _push(left, "equal", CELL_SEPARATOR)
            left_seen = True
            if cell.kind == "equal":
                _push(left, "equal", cell.left)
            elif cell.left_inline is not None:
                for segment in cell.left_inline:
                    _push(left, segment.kind, segment.text)
            else:
                _push(left, "delete", cell.left)
        if cell.right is not None:
            if right_seen:
                _push(right, "equal", CELL_SEPARATOR)
            right_seen = True
            if cell.kind == "equal":
                _push(right, "equal", cell.right)
            elif cell.right_inline is not None:
                for segment in cell.right_inline:
                    _push(right, segment.kind, segment.text)
            else:
                _push(right, "insert", cell.right)
    return left, right


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

_MARK_FLAGS = ("bold", "italic", "underline", "strike")


def _word_flags(text: str, marks: list[Any]) -> dict[str, frozenset[int]]:
    """For each flag, the indexes of the words it covers."""
    words = [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
    out: dict[str, set[int]] = {}
    for start, end, flags in marks:
        for index, (ws, we) in enumerate(words):
            if ws < end and we > start:
                for flag in flags:
                    out.setdefault(str(flag), set()).add(index)
    return {flag: frozenset(indexes) for flag, indexes in out.items()}


def format_changes(a: Line, b: Line) -> list[str]:
    """Formatting differences between two lines whose text is equal."""
    sa, sb = a.style or {}, b.style or {}
    changes: list[str] = []
    if sa.get("heading") != sb.get("heading"):
        changes.append("heading")
    if sa.get("style") != sb.get("style") and (sa.get("style") or sb.get("style")):
        changes.append("style")
    if sa.get("list") != sb.get("list") and (sa.get("list") is None) != (sb.get("list") is None):
        changes.append("list")

    if "marks" in sa or "marks" in sb:
        fa = _word_flags(a.text, sa.get("marks") or [])
        fb = _word_flags(b.text, sb.get("marks") or [])
        for flag in _MARK_FLAGS:
            if fa.get(flag, frozenset()) != fb.get(flag, frozenset()):
                changes.append(flag)
        styles_a = {k for k in fa if k.startswith("style:")}
        styles_b = {k for k in fb if k.startswith("style:")}
        if any(fa.get(k) != fb.get(k) for k in styles_a | styles_b):
            changes.append("character_style")
    else:
        for flag in ("bold", "italic"):
            if bool(sa.get(flag)) != bool(sb.get(flag)):
                changes.append(flag)
        size_a, size_b = sa.get("size"), sb.get("size")
        if size_a and size_b and abs(float(size_a) - float(size_b)) > 0.6:
            changes.append("size")
        font_a, font_b = sa.get("font"), sb.get("font")
        if font_a and font_b and font_a != font_b and "bold" not in changes and "italic" not in changes:
            changes.append("font")
    return changes
