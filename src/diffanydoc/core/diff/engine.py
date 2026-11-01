"""The comparison engine: line alignment, inline refinement, statistics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Sequence

from ..adapters import adapters, load
from ..model import DiffResult, Document, Line, OcrStats, Row, Stats
from ..ocr import OcrOptions, apply_ocr
from ..visual import VisualOptions, compare_pdf_pages
from .align import align_pages
from .lines import cell_diff, document_lines, inline_diff, line_similarity


@dataclass(slots=True)
class DiffOptions:
    #: Identical rows kept on each side of a change.
    context: int = 3
    case_sensitive: bool = True
    collapse_whitespace: bool = True
    #: Minimum similarity for two changed lines to be shown side by side.
    pair_threshold: float = 0.4
    #: Fold long unchanged runs (HTML report). The API asks for full rows.
    fold_equal: bool = True
    #: Render both PDFs and compare pixels, not just extracted text.
    visual: bool = False
    #: Visual layer tuning; only used when ``visual`` is true.
    visual_dpi: int = 96
    visual_tolerance: int = 24
    visual_shift_pt: float = 4.0
    visual_max_pages: int = 60
    #: OCR pages without a text layer (scanned PDFs, needs Tesseract).
    ocr: bool = False
    ocr_language: str = "eng"
    ocr_dpi: int = 300
    ocr_min_chars: int = 8
    ocr_max_pages: int = 60
    #: None = per-user cache directory (``DIFFANYDOC_CACHE_DIR`` overrides).
    ocr_cache_dir: str | None = None


def compare(
    left: str | Path | Document,
    right: str | Path | Document,
    options: DiffOptions | None = None,
) -> DiffResult:
    """Compare two files (or two already-loaded documents)."""
    options = options or DiffOptions()
    left_doc = _coerce(left)
    right_doc = _coerce(right)

    ocr: OcrStats | None = None
    if options.ocr:
        ocr_options = OcrOptions(
            language=options.ocr_language,
            dpi=options.ocr_dpi,
            min_text_chars=options.ocr_min_chars,
            max_pages=options.ocr_max_pages,
            cache_dir=options.ocr_cache_dir,
        )
        for document in (left_doc, right_doc):
            page_stats = apply_ocr(document, ocr_options)
            if page_stats is None:
                continue
            ocr = page_stats if ocr is None else ocr.merged(page_stats)

    left_lines = document_lines(
        left_doc,
        case_sensitive=options.case_sensitive,
        collapse_whitespace=options.collapse_whitespace,
    )
    right_lines = document_lines(
        right_doc,
        case_sensitive=options.case_sensitive,
        collapse_whitespace=options.collapse_whitespace,
    )

    rows = _build_rows(left_lines, right_lines, options)
    stats = _stats(left_lines, right_lines, rows)
    if options.fold_equal:
        rows = _fold_equal_runs(rows, options.context)

    page_map = align_pages(left_doc, right_doc)
    visual = None
    if options.visual and left_doc.kind == "pdf" and right_doc.kind == "pdf":
        visual = compare_pdf_pages(
            left_doc.path,
            right_doc.path,
            page_map,
            VisualOptions(
                dpi=options.visual_dpi,
                tolerance=options.visual_tolerance,
                max_shift_pt=options.visual_shift_pt,
                max_pages=options.visual_max_pages,
            ),
        )

    return DiffResult(
        left_path=left_doc.path,
        right_path=right_doc.path,
        left_kind=left_doc.kind,
        right_kind=right_doc.kind,
        rows=rows,
        page_map=page_map,
        stats=stats,
        visual=visual,
        ocr=ocr,
        options=asdict(options),
    )


def _coerce(source: str | Path | Document) -> Document:
    if isinstance(source, Document):
        return source
    return load(source)


# --------------------------------------------------------------------------- #
# Row construction
# --------------------------------------------------------------------------- #


def _build_rows(
    left: Sequence[Line], right: Sequence[Line], options: DiffOptions
) -> list[Row]:
    matcher = SequenceMatcher(
        None,
        [line.norm for line in left],
        [line.norm for line in right],
        autojunk=False,
    )
    rows: list[Row] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rows.extend(_equal_row(a, b) for a, b in zip(left[i1:i2], right[j1:j2]))
            continue
        if tag == "delete":
            rows.extend(_single_row(a, None, "delete") for a in left[i1:i2])
            continue
        if tag == "insert":
            rows.extend(_single_row(None, b, "insert") for b in right[j1:j2])
            continue
        rows.extend(
            _refine_replacement(left[i1:i2], right[j1:j2], options.pair_threshold)
        )
    return rows


def _equal_row(left: Line, right: Line) -> Row:
    return Row(kind="equal", left=left, right=right)


def _single_row(left: Line | None, right: Line | None, kind: str) -> Row:
    return Row(kind=kind, left=left, right=right)  # type: ignore[arg-type]


def _replace_row(left: Line, right: Line) -> Row:
    if left.cells is not None and right.cells is not None:
        left_inline, right_inline = cell_diff(left.cells, right.cells)
    else:
        left_inline, right_inline = inline_diff(left.text, right.text)
    return Row(
        kind="replace",
        left=left,
        right=right,
        left_inline=left_inline,
        right_inline=right_inline,
    )


def _refine_replacement(
    left: Sequence[Line], right: Sequence[Line], threshold: float
) -> list[Row]:
    """Pair up changed lines so a rewrite does not look like delete+insert.

    A small look-ahead decides which side owns an unmatched line, which is what
    makes side-by-side views readable.
    """
    rows: list[Row] = []
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        if line_similarity(a, b) >= threshold:
            rows.append(_replace_row(a, b))
            i += 1
            j += 1
            continue

        ahead_left = (
            line_similarity(left[i + 1], b) if i + 1 < len(left) else -1.0
        )
        ahead_right = (
            line_similarity(a, right[j + 1]) if j + 1 < len(right) else -1.0
        )
        if ahead_right >= ahead_left:
            rows.append(_single_row(a, None, "delete"))
            i += 1
        else:
            rows.append(_single_row(None, b, "insert"))
            j += 1

    rows.extend(_single_row(a, None, "delete") for a in left[i:])
    rows.extend(_single_row(None, b, "insert") for b in right[j:])
    return rows


# --------------------------------------------------------------------------- #
# Statistics and folding
# --------------------------------------------------------------------------- #


def _stats(left: Sequence[Line], right: Sequence[Line], rows: Sequence[Row]) -> Stats:
    added = sum(1 for row in rows if row.kind == "insert")
    removed = sum(1 for row in rows if row.kind == "delete")
    changed = sum(1 for row in rows if row.kind == "replace")

    left_chars = sum(len(line.text) for line in left)
    right_chars = sum(len(line.text) for line in right)
    total = left_chars + right_chars

    # Matched characters, counting equal rows twice and the unchanged parts of
    # refined rows. This is what a reader intuitively calls "benzerlik": four
    # changed numbers in a contract should not read as 30% similar.
    matched = 0
    for row in rows:
        if row.kind == "equal" and row.left and row.right:
            matched += len(row.left.text) + len(row.right.text)
        elif row.kind == "replace" and row.left_inline:
            matched += 2 * sum(
                len(segment.text)
                for segment in row.left_inline
                if segment.kind == "equal"
            )

    similarity = min(matched / total, 1.0) if total else 1.0

    return Stats(
        left_lines=len(left),
        right_lines=len(right),
        added=added,
        removed=removed,
        changed=changed,
        similarity=similarity,
    )


def _fold_equal_runs(rows: Sequence[Row], context: int) -> list[Row]:
    """Replace long runs of identical rows with a gap marker."""
    keep = max(context, 0)
    out: list[Row] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        if row.kind != "equal":
            out.append(row)
            index += 1
            continue

        end = index
        while end < len(rows) and rows[end].kind == "equal":
            end += 1
        run = rows[index:end]
        if len(run) <= 2 * keep + 1:
            out.extend(run)
        else:
            out.extend(run[:keep])
            hidden = run[keep:-keep] if keep else run
            following = run[-keep] if keep else None
            gap = len(hidden)
            if following is not None:
                following.hidden_before = gap
                out.append(following)
            else:  # pragma: no cover - covered by the length check
                anchor = Row(kind="equal", hidden_before=gap)
                out.append(anchor)
        index = end
    return out


def supported_formats() -> list[dict[str, str]]:
    return [
        {
            "name": adapter.name,
            "extensions": ", ".join(adapter.extensions[:8])
            + (", ..." if len(adapter.extensions) > 8 else ""),
        }
        for adapter in adapters()
    ]


def result_as_dict(result: DiffResult) -> dict[str, Any]:
    from ..report.json import result_to_dict

    return result_to_dict(result)
