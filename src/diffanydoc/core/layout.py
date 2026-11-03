"""Geometry-aware block operations shared by the PDF and OCR paths.

Visual lines are what a PDF gives us, but they are a poor unit to compare:
adding one word to a paragraph re-wraps every following line, and a line-based
diff then reports the whole paragraph as changed. :func:`reflow` joins the
visual lines of a paragraph back into one block, keeping per-word spans so
the viewer can still box the exact words that changed on the page.
"""

from __future__ import annotations

from typing import Iterable

from .model import BBox, Block, Span


def union(boxes: Iterable[BBox]) -> BBox | None:
    boxes = list(boxes)
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def make_line(words: list[tuple[str, BBox]], page: int, **extra) -> Block:
    """Build a text block from ``(word, bbox)`` pairs in reading order."""
    parts: list[str] = []
    spans: list[Span] = []
    offset = 0
    for word, box in words:
        if parts:
            parts.append(" ")
            offset += 1
        parts.append(word)
        spans.append(Span(offset, offset + len(word), page, box))
        offset += len(word)
    return Block(
        kind="text",
        text="".join(parts),
        bbox=union(box for _, box in words),
        spans=spans,
        **extra,
    )


def _append(target: Block, other: Block, separator: str) -> None:
    """Concatenate ``other`` onto ``target`` and shift its spans."""
    shift = len(target.text) + len(separator)
    target.text = target.text + separator + other.text
    target.spans = target.spans + [
        Span(s.start + shift, s.end + shift, s.page, s.bbox) for s in other.spans
    ]
    boxes = [b for b in (target.bbox, other.bbox) if b is not None]
    # Only union boxes on the same page; the block keeps its first page box.
    if target.spans and other.spans and target.spans[0].page != other.spans[0].page:
        return
    target.bbox = union(boxes)


def _hyphen_break(first: str, second: str) -> bool:
    return (
        first.endswith("-")
        and not first.endswith("--")
        and len(first) > 1
        and first[-2].isalpha()
        and second[:1].islower()
    )


def _join(target: Block, other: Block) -> None:
    if _hyphen_break(target.text, other.text):
        # Drop the hyphen: "inter-" + "national" -> "international". The span
        # of the hyphenated fragment keeps its own box, so both halves of the
        # word are still marked on the page.
        target.text = target.text[:-1]
        if target.spans and target.spans[-1].end > len(target.text):
            last = target.spans[-1]
            target.spans[-1] = Span(last.start, len(target.text), last.page, last.bbox)
        _append(target, other, "")
        target.style = {**target.style, "joined_hyphen": True}
    else:
        _append(target, other, " ")


def merge_hyphenation(blocks: list[Block]) -> list[Block]:
    """Join lines that were split by a hyphen at the line end.

    Returns a new list; a merged line disappears instead of shifting the text
    of every following line.
    """
    out: list[Block] = []
    for block in blocks:
        if (
            out
            and block.kind == "text"
            and out[-1].kind == "text"
            and out[-1].cells is None
            and block.cells is None
            and _hyphen_break(out[-1].text, block.text)
        ):
            _join(out[-1], block)
        else:
            out.append(block)
    return out


# --------------------------------------------------------------------------- #
# Paragraph reflow
# --------------------------------------------------------------------------- #


#: A line that wrapped spans at least this share of the text column.
MIN_WRAPPED_SHARE = 0.6


def _size(block: Block) -> float:
    size = block.style.get("size") if block.style else None
    if size:
        return float(size)
    if block.bbox:
        return max(block.bbox[3] - block.bbox[1], 1.0)
    return 10.0


def _is_columnar(block: Block) -> bool:
    """Lines with wide internal gaps are table rows or columns: never join."""
    size = _size(block)
    for before, after in zip(block.spans, block.spans[1:]):
        if before.page != after.page:
            continue
        if after.bbox[0] - before.bbox[2] > 2.2 * size:
            return True
    return False


def reflow(blocks: list[Block], page_width: float = 0.0) -> list[Block]:
    """Join the visual lines of each paragraph into one block.

    A line continues into the next one when it *wrapped*: it reaches the right
    edge of the text column, the next line starts at the column's left edge,
    the vertical gap is a normal line gap and the font size matches. Short
    lines (headings, list items, table rows, the last line of a paragraph)
    therefore always end their paragraph.
    """
    text_blocks = [b for b in blocks if b.kind == "text" and b.bbox is not None]
    if len(text_blocks) < 2:
        return list(blocks)

    lefts = [b.bbox[0] for b in text_blocks]  # type: ignore[index]
    # Lines never run past the column's right margin, so the widest line is
    # the best estimate of it. An outlier (a page number in the margin) only
    # makes joining *less* likely, never wrong.
    right_edge = max(b.bbox[2] for b in text_blocks)  # type: ignore[index]
    left_edge = min(lefts)
    # Width a full line can have: the page minus symmetric margins when the
    # page size is known. A wrapped line fills most of it; this stops two
    # short lines (a heading over a date) from being joined on a page where
    # no line is long.
    available = (page_width - 2 * left_edge) if page_width > 2 * left_edge else 0.0
    available = max(available, right_edge - left_edge)
    min_wrapped = left_edge + MIN_WRAPPED_SHARE * available

    out: list[Block] = []
    previous: Block | None = None  # last visual line appended to out[-1]
    for block in blocks:
        if (
            previous is not None
            and out
            and previous.bbox is not None
            and previous.bbox[2] >= min_wrapped
            and _continues(previous, block, left_edge, right_edge)
        ):
            current = out[-1]
            _join(current, block)
            current.style = {**current.style, "reflowed": True}
            previous = block
            continue
        if block.kind == "text" and block.bbox is not None and block.cells is None:
            copy = Block(
                kind=block.kind,
                text=block.text,
                bbox=block.bbox,
                style=dict(block.style),
                children=block.children,
                source_ref=dict(block.source_ref),
                spans=list(block.spans),
                cells=None,
                label=block.label,
            )
            out.append(copy)
            previous = block
        else:
            out.append(block)
            previous = None
    return out


def _continues(line: Block, nxt: Block, left_edge: float, right_edge: float) -> bool:
    if nxt.kind != "text" or nxt.bbox is None or line.bbox is None:
        return False
    if nxt.cells is not None or line.cells is not None:
        return False
    if not line.text.strip() or not nxt.text.strip():
        return False
    size_a, size_b = _size(line), _size(nxt)
    if abs(size_a - size_b) > 0.6:
        return False
    if bool(line.style.get("bold")) != bool(nxt.style.get("bold")):
        return False
    height = max(line.bbox[3] - line.bbox[1], size_a * 0.8)
    gap = nxt.bbox[1] - line.bbox[3]
    if gap < -0.5 * height or gap > 0.9 * height:
        return False
    tolerance = max(2.5 * size_a, 0.02 * (right_edge - left_edge))
    # The line must have wrapped: the next line's first word would not have
    # fitted after it. This works for justified and ragged-right text alike.
    first_word = nxt.spans[0].bbox if nxt.spans else nxt.bbox
    first_width = first_word[2] - first_word[0]
    space = 0.25 * size_a
    if line.bbox[2] + space + first_width <= right_edge + 0.5:
        return False
    # A sentence end followed by a capital is ambiguous (a new paragraph
    # without spacing, or a wrapped sentence): then demand a full line.
    if line.text.rstrip().endswith((".", ":", ";", "!", "?")) and (
        nxt.text[:1].isupper() or nxt.text[:1].isdigit()
    ):
        if line.bbox[2] < right_edge - tolerance:
            return False
    # The next line starts back at the paragraph's left edge (a first-line
    # indent is allowed on the line itself, not on the next one).
    if nxt.bbox[0] > line.bbox[0] + tolerance and nxt.bbox[0] > left_edge + tolerance:
        return False
    if _is_columnar(line) or _is_columnar(nxt):
        return False
    # A short label line ending with ":" usually introduces a list.
    if line.text.rstrip().endswith(":") and len(line.text) < 40:
        return False
    return True
