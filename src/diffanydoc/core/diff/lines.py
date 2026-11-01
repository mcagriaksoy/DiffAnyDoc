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
    """Flatten all text blocks into a single sequence of comparable lines.

    Page order is preserved and each line keeps its page index and bbox, which
    is what lets the viewer jump from a diff straight to the page position.
    """
    lines: list[Line] = []
    for page in document.pages:
        for block in page.blocks:
            if block.kind != "text":
                continue
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
