"""Turn a document into display lines, and compare two lines' contents."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..layout import reflow as reflow_blocks
from ..model import Document, Line, Segment
from ..normalize import normalize_line

_WORD = re.compile(r"\S+|\s+")


def style_summary(style: dict[str, object] | None) -> str:
    """Short human-readable formatting signature for style comparison."""
    if not style:
        return ""
    tokens: list[str] = []
    if style.get("heading"):
        tokens.append(str(style.get("paragraph_style") or "heading"))
    if style.get("bold"):
        tokens.append("bold")
    if style.get("italic"):
        tokens.append("italic")
    if style.get("underline"):
        tokens.append("underline")
    if style.get("strike"):
        tokens.append("strike")
    size = style.get("size")
    if isinstance(size, (int, float)) and size > 0:
        tokens.append(f"{float(size):g}pt")
    font = str(style.get("font") or "").strip()
    if font:
        # Strip subset prefix like "ABCDEF+Helvetica-Bold" -> "Helvetica"
        clean_font = font.split("+")[-1].split("-")[0].strip()
        if clean_font:
            tokens.append(clean_font)
    return ", ".join(tokens)


def document_lines(
    document: Document,
    *,
    case_sensitive: bool = True,
    collapse_whitespace: bool = True,
    compare_formatting: bool = False,
    reflow: bool = True,
) -> list[Line]:
    """Flatten all text and table rows into a single sequence of lines.

    Page order is preserved and each line keeps its page index and bbox, which
    is what lets the viewer jump from a diff straight to the page position.
    Table rows become one line each and keep their cells, so the diff can
    align columns individually.
    """
    lines: list[Line] = []
    for page in document.pages:
        blocks = page.blocks
        if reflow and any(b.bbox is not None for b in blocks):
            blocks = reflow_blocks(blocks, page.width)
        for block in blocks:
            if block.kind == "text":
                norm = normalize_line(
                    block.text,
                    case_sensitive=case_sensitive,
                    collapse_whitespace=collapse_whitespace,
                )
                style = dict(block.style)
                if compare_formatting:
                    sig = style_summary(style)
                    if sig:
                        style["summary"] = sig
                lines.append(
                    Line(
                        text=block.text,
                        norm=norm,
                        page=page.index,
                        number=len(lines) + 1,
                        bbox=block.bbox,
                        style=style,
                        spans=list(block.spans),
                        cells=block.cells,
                        label=block.label,
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
                            bbox=row.bbox or block.bbox,
                            style={**row.style, "table": True},
                            cells=[cell.text for cell in row.children],
                        )
                    )
    return lines


def line_similarity(a: Line, b: Line) -> float:
    """0..1 similarity between two lines, used to pair changed rows."""
    len_a = len(a.norm)
    len_b = len(b.norm)
    if len_a == 0 and len_b == 0:
        return 1.0
    if len_a == 0 or len_b == 0:
        return 0.0
    if 2.0 * min(len_a, len_b) / (len_a + len_b) < 0.35:
        return 0.0
    try:
        if len_a + len_b > 300:
            a_tok = a.norm.split()
            b_tok = b.norm.split()
            return SequenceMatcher(None, a_tok, b_tok, autojunk=True).ratio()
        matcher = SequenceMatcher(None, a.norm, b.norm, autojunk=False)
        if matcher.quick_ratio() < 0.35:
            return 0.0
        return matcher.ratio()
    except TypeError:  # pragma: no cover - defensive
        return 0.0


def inline_diff(
    left: str, right: str
) -> tuple[list[Segment], list[Segment]]:
    """Word-level diff inside a pair of changed lines.

    Whitespace is kept as its own token so the reconstructed text is exact.
    Normalized word keys are compared first so smart-quote or case/spacing
    variations do not cause the entire paragraph to look replaced.
    """
    a_tokens = _WORD.findall(left)
    b_tokens = _WORD.findall(right)
    a_keys = [
        " " if tok.isspace() else normalize_line(tok, collapse_whitespace=False)
        for tok in a_tokens
    ]
    b_keys = [
        " " if tok.isspace() else normalize_line(tok, collapse_whitespace=False)
        for tok in b_tokens
    ]
    matcher = SequenceMatcher(None, a_keys, b_keys, autojunk=False)

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
            for a_tok, b_tok in zip(a_tokens[i1:i2], b_tokens[j1:j2]):
                if a_tok == b_tok or (a_tok.isspace() and b_tok.isspace() and a_tok == b_tok):
                    push(left_segments, "equal", a_tok)
                    push(right_segments, "equal", b_tok)
                elif normalize_line(a_tok, collapse_whitespace=False) == normalize_line(b_tok, collapse_whitespace=False) and not a_tok.isspace():
                    push(left_segments, "equal", a_tok)
                    push(right_segments, "equal", b_tok)
                else:
                    push(left_segments, "delete", a_tok)
                    push(right_segments, "insert", b_tok)
        elif tag == "replace":
            # Refine punctuation-attached tokens (e.g. "word," vs "word.")
            for a_sub, b_sub in [_subtoken_diff("".join(a_tokens[i1:i2]), "".join(b_tokens[j1:j2]))]:
                for seg in a_sub:
                    push(left_segments, seg.kind, seg.text)
                for seg in b_sub:
                    push(right_segments, seg.kind, seg.text)
        else:
            push(left_segments, "delete", "".join(a_tokens[i1:i2]))
            push(right_segments, "insert", "".join(b_tokens[j1:j2]))
    return _coalesce_whitespace_segments(left_segments), _coalesce_whitespace_segments(right_segments)


def _coalesce_whitespace_segments(segments: list[Segment]) -> list[Segment]:
    """Merge whitespace-only 'equal' segments surrounded by identical change kinds.

    Prevents a single space between two replaced words (e.g. 'yazılım geliştirme'
    -> 'donanım kurulum') from matching as an isolated 'equal' space and splitting
    a contiguous multi-word change into fragmented single-word diffs.
    """
    if len(segments) < 3:
        return segments
    out: list[Segment] = []
    i = 0
    n = len(segments)
    while i < n:
        cur = segments[i]
        if (
            cur.kind == "equal"
            and cur.text.isspace()
            and out
            and out[-1].kind in ("delete", "insert")
            and i + 1 < n
            and segments[i + 1].kind == out[-1].kind
        ):
            out[-1].text += cur.text + segments[i + 1].text
            i += 2
            continue
        if out and out[-1].kind == cur.kind:
            out[-1].text += cur.text
        else:
            out.append(Segment(kind=cur.kind, text=cur.text))
        i += 1
    return out


_SUBWORD = re.compile(r"\w+|[^\w]+")


def _subtoken_diff(left: str, right: str) -> tuple[list[Segment], list[Segment]]:
    """Refine a replaced word span by splitting words from attached punctuation."""
    a_sub = _SUBWORD.findall(left)
    b_sub = _SUBWORD.findall(right)
    if len(a_sub) <= 1 and len(b_sub) <= 1:
        return (
            [Segment(kind="delete", text=left)] if left else [],
            [Segment(kind="insert", text=right)] if right else [],
        )
    matcher = SequenceMatcher(None, a_sub, b_sub, autojunk=False)
    l_out: list[Segment] = []
    r_out: list[Segment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" and not "".join(a_sub[i1:i2]).isspace():
            l_out.append(Segment(kind="equal", text="".join(a_sub[i1:i2])))
            r_out.append(Segment(kind="equal", text="".join(b_sub[j1:j2])))
        else:
            if i1 < i2:
                l_out.append(Segment(kind="delete", text="".join(a_sub[i1:i2])))
            if j1 < j2:
                r_out.append(Segment(kind="insert", text="".join(b_sub[j1:j2])))
    return _coalesce_whitespace_segments(l_out), _coalesce_whitespace_segments(r_out)


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
