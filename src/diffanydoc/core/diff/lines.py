"""Turn a document into display lines, and compare two lines' contents."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..model import Document, Line, Segment
from ..normalize import normalize_line

_WORD = re.compile(r"\S+|\s+")


def document_lines(
    document: Document,
    *,
    case_sensitive: bool = True,
    collapse_whitespace: bool = True,
) -> list[Line]:
    """Flatten all text and table rows into a single sequence of lines.

    Page order is preserved and each line keeps its page index and bbox, which
    is what lets the viewer jump from a diff straight to the page position.
    Table rows become one line each and keep their cells, so the diff can
    align columns individually.
    """
    lines: list[Line] = []
    for page in document.pages:
        for block in page.blocks:
            if block.kind == "text":
                lines.append(
                    Line(
                        text=block.text,
                        norm=normalize_line(
                            block.text,
                            case_sensitive=case_sensitive,
                            collapse_whitespace=collapse_whitespace,
                        ),
                        page=page.index,
                        number=len(lines) + 1,
                        bbox=block.bbox,
                        style=block.style,
                    )
                )
            elif block.kind == "table":
                for row in block.children:
                    if row.kind != "table_row":
                        continue
                    text = row.text or " | ".join(
                        cell.text for cell in row.children
                    )
                    lines.append(
                        Line(
                            text=text,
                            norm=normalize_line(
                                text,
                                case_sensitive=case_sensitive,
                                collapse_whitespace=collapse_whitespace,
                            ),
                            page=page.index,
                            number=len(lines) + 1,
                            style={**row.style, "table": True},
                            cells=[cell.text for cell in row.children],
                        )
                    )
    return lines


def line_similarity(a: Line, b: Line) -> float:
    """0..1 similarity between two lines, used to pair changed rows."""
    try:
        return SequenceMatcher(None, a.norm, b.norm, autojunk=False).ratio()
    except TypeError:  # pragma: no cover - defensive
        return 0.0


def inline_diff(
    left: str, right: str
) -> tuple[list[Segment], list[Segment]]:
    """Word-level diff inside a pair of changed lines.

    Whitespace is kept as its own token so the reconstructed text is exact.
    """
    a_tokens = _WORD.findall(left)
    b_tokens = _WORD.findall(right)
    matcher = SequenceMatcher(None, a_tokens, b_tokens, autojunk=False)

    left_segments: list[Segment] = []
    right_segments: list[Segment] = []

    def push(target: list[Segment], kind: str, text: str) -> None:
        if not text:
            return
        if target and target[-1].kind == kind:
            target[-1].text += text
        else:
            target.append(Segment(kind=kind, text=text))  # type: ignore[arg-type]

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            push(left_segments, "equal", "".join(a_tokens[i1:i2]))
            push(right_segments, "equal", "".join(b_tokens[j1:j2]))
        else:
            push(left_segments, "delete", "".join(a_tokens[i1:i2]))
            push(right_segments, "insert", "".join(b_tokens[j1:j2]))
    return left_segments, right_segments


def cell_diff(
    left: list[str], right: list[str], sep: str = " | "
) -> tuple[list[Segment], list[Segment]]:
    """Word-level diff of two table rows, aligned cell by cell.

    Cells are matched with the same LCS used for lines, so inserting a column
    does not mark every later cell as changed. Each side's segments rebuild
    that side's own ``sep.join(cells)`` exactly.
    """
    matcher = SequenceMatcher(
        None,
        [normalize_line(cell) for cell in left],
        [normalize_line(cell) for cell in right],
        autojunk=False,
    )
    left_segments: list[Segment] = []
    right_segments: list[Segment] = []
    have_left = False
    have_right = False

    def push(target: list[Segment], kind: str, text: str) -> None:
        if not text:
            return
        if target and target[-1].kind == kind:
            target[-1].text += text
        else:
            target.append(Segment(kind=kind, text=text))  # type: ignore[arg-type]

    def add_left(kind: str, text: str) -> None:
        nonlocal have_left
        if have_left:
            push(left_segments, "equal", sep)
        have_left = True
        push(left_segments, kind, text)

    def add_right(kind: str, text: str) -> None:
        nonlocal have_right
        if have_right:
            push(right_segments, "equal", sep)
        have_right = True
        push(right_segments, kind, text)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for a, b in zip(left[i1:i2], right[j1:j2]):
                add_left("equal", a)
                add_right("equal", b)
        elif tag == "replace":
            for offset in range(max(i2 - i1, j2 - j1)):
                a = left[i1 + offset] if i1 + offset < i2 else None
                b = right[j1 + offset] if j1 + offset < j2 else None
                if a is not None and b is not None:
                    left_inline, right_inline = inline_diff(a, b)
                    if have_left:
                        push(left_segments, "equal", sep)
                    have_left = True
                    left_segments.extend(left_inline)
                    if have_right:
                        push(right_segments, "equal", sep)
                    have_right = True
                    right_segments.extend(right_inline)
                elif a is not None:
                    add_left("delete", a)
                elif b is not None:
                    add_right("insert", b)
        elif tag == "delete":
            for cell in left[i1:i2]:
                add_left("delete", cell)
        else:
            for cell in right[j1:j2]:
                add_right("insert", cell)
    return left_segments, right_segments
