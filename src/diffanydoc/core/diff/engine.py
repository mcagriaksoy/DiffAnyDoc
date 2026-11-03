"""The comparison engine: line alignment, inline refinement, statistics."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, Sequence

from ..adapters import LoadOptions, adapters, load
from ..model import DiffResult, Document, DocumentInfo, Line, Row, Stats
from .align import align_pages
from .lines import (
    cell_diff,
    cells_to_inline,
    document_lines,
    format_changes,
    inline_diff,
    line_similarity,
)

VisualMode = Literal["off", "auto", "on"]
#: A look-ahead match must beat the current pairing by this much to win.
_CLEARLY_BETTER = 0.15


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
    #: Join the visual lines of a paragraph (PDF/OCR) before comparing, so a
    #: re-wrapped paragraph only shows the words that really changed.
    reflow: bool = True
    #: Also report rows whose text is equal but whose formatting changed.
    compare_formatting: bool = False
    #: Pixel comparison of rendered pages. "auto" runs it when there is little
    #: or no text to compare (images, scans).
    visual: VisualMode = "auto"
    visual_dpi: int = 100
    visual_tolerance: int = 40
    #: OCR for pages without a text layer: "auto", "off" or "force".
    ocr: str = "auto"
    ocr_lang: str | None = None

    def load_options(self) -> LoadOptions:
        return LoadOptions(ocr=self.ocr, ocr_lang=self.ocr_lang)  # type: ignore[arg-type]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare(
    left: str | Path | Document,
    right: str | Path | Document,
    options: DiffOptions | None = None,
) -> DiffResult:
    """Compare two files (or two already-loaded documents)."""
    result, _, _ = compare_documents(left, right, options)
    return result


def compare_documents(
    left: str | Path | Document,
    right: str | Path | Document,
    options: DiffOptions | None = None,
) -> tuple[DiffResult, Document, Document]:
    """Like :func:`compare`, but also return the loaded documents.

    The API needs the documents afterwards (page sizes, rendering, visual
    diff); returning them avoids reading — and possibly OCR-ing — twice.
    """
    options = options or DiffOptions()
    load_options = options.load_options()

    left_hash = file_sha256(Path(left)) if not isinstance(left, Document) else ""
    right_hash = file_sha256(Path(right)) if not isinstance(right, Document) else ""
    byte_identical = bool(left_hash) and left_hash == right_hash

    left_doc = _coerce(left, load_options)
    # Byte-identical files: read once. The content is the same by definition.
    right_doc = (
        _same_content(left_doc, Path(right))
        if byte_identical
        else _coerce(right, load_options)
    )

    line_options = dict(
        case_sensitive=options.case_sensitive,
        collapse_whitespace=options.collapse_whitespace,
        reflow=options.reflow,
    )
    left_lines = document_lines(left_doc, **line_options)
    right_lines = (
        left_lines if byte_identical else document_lines(right_doc, **line_options)
    )

    if byte_identical:
        rows = [Row(kind="equal", left=line, right=line) for line in left_lines]
    else:
        rows = _build_rows(left_lines, right_lines, options)
    stats = _stats(left_lines, right_lines, rows)
    page_map = align_pages(left_doc, right_doc)

    result = DiffResult(
        left_path=left_doc.path,
        right_path=Path(right) if byte_identical else right_doc.path,
        left_kind=left_doc.kind,
        right_kind=right_doc.kind,
        rows=rows,
        page_map=page_map,
        stats=stats,
        options=asdict(options),
        left_info=DocumentInfo.of(left_doc, left_hash),
        right_info=DocumentInfo.of(right_doc, right_hash),
        byte_identical=byte_identical,
    )

    if not byte_identical and _wants_visual(options, left_doc, right_doc, page_map):
        from ..visual import VisualOptions, compare_documents as visual_compare

        result.visual = visual_compare(
            left_doc,
            right_doc,
            page_map,
            VisualOptions(dpi=options.visual_dpi, tolerance=options.visual_tolerance),
        )
        result.stats.visual_regions = sum(len(page.regions) for page in result.visual)
    elif byte_identical and options.visual == "on":
        result.visual = []

    if options.fold_equal:
        result.rows = fold_equal_runs(rows, options.context)
    return result, left_doc, right_doc


def _coerce(source: str | Path | Document, options: LoadOptions) -> Document:
    if isinstance(source, Document):
        return source
    return load(source, options)


def _same_content(document: Document, path: Path) -> Document:
    return Document(
        path=path,
        kind=document.kind,
        pages=document.pages,
        meta=dict(document.meta),
        warnings=list(document.warnings),
    )


def _wants_visual(
    options: DiffOptions, left: Document, right: Document, page_map: Sequence[Any]
) -> bool:
    if options.visual == "off" or not (left.renderable and right.renderable):
        return False
    if options.visual == "on":
        return True
    # auto: images, and documents where some page has no real text layer.
    if left.kind == "image" or right.kind == "image":
        return True
    return any(page.source != "text" for page in left.pages + right.pages)


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
            for a, b in zip(left[i1:i2], right[j1:j2]):
                row = Row(kind="equal", left=a, right=b)
                if options.compare_formatting:
                    row.format_changes = format_changes(a, b) or None
                rows.append(row)
            continue
        if tag == "delete":
            rows.extend(Row(kind="delete", left=a) for a in left[i1:i2])
            continue
        if tag == "insert":
            rows.extend(Row(kind="insert", right=b) for b in right[j1:j2])
            continue
        rows.extend(_refine_replacement(left[i1:i2], right[j1:j2], options))
    return rows


def _replace_row(left: Line, right: Line, options: DiffOptions) -> Row:
    if left.cells is not None and right.cells is not None:
        cells = cell_diff(
            left,
            right,
            case_sensitive=options.case_sensitive,
            collapse_whitespace=options.collapse_whitespace,
        )
        left_inline, right_inline = cells_to_inline(cells)
        return Row(
            kind="replace",
            left=left,
            right=right,
            left_inline=left_inline,
            right_inline=right_inline,
            cells=cells,
        )
    left_inline, right_inline = inline_diff(
        left.text, right.text, case_sensitive=options.case_sensitive
    )
    return Row(
        kind="replace",
        left=left,
        right=right,
        left_inline=left_inline,
        right_inline=right_inline,
    )


def _refine_replacement(
    left: Sequence[Line], right: Sequence[Line], options: DiffOptions
) -> list[Row]:
    """Pair up changed lines so a rewrite does not look like delete+insert.

    A small look-ahead decides which side owns an unmatched line, which is what
    makes side-by-side views readable.
    """
    threshold = options.pair_threshold
    rows: list[Row] = []
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        current = line_similarity(a, b)
        ahead_left = line_similarity(left[i + 1], b) if i + 1 < len(left) else -1.0
        ahead_right = line_similarity(a, right[j + 1]) if j + 1 < len(right) else -1.0
        if current >= threshold and max(ahead_left, ahead_right) <= current + _CLEARLY_BETTER:
            rows.append(_replace_row(a, b, options))
            i += 1
            j += 1
            continue
        if max(ahead_left, ahead_right) < threshold and len(left) - i == len(right) - j:
            # Equal-sized blocks where nothing lines up: a rewritten line is
            # still easier to read side by side than as delete + insert.
            rows.append(_replace_row(a, b, options))
            i += 1
            j += 1
        elif ahead_right > ahead_left:
            # ``a`` lines up with the next right line: ``b`` was inserted.
            rows.append(Row(kind="insert", right=b))
            j += 1
        else:
            # The next left line lines up with ``b`` (or nothing does).
            rows.append(Row(kind="delete", left=a))
            i += 1

    rows.extend(Row(kind="delete", left=a) for a in left[i:])
    rows.extend(Row(kind="insert", right=b) for b in right[j:])
    return rows


# --------------------------------------------------------------------------- #
# Statistics and folding
# --------------------------------------------------------------------------- #


def _stats(left: Sequence[Line], right: Sequence[Line], rows: Sequence[Row]) -> Stats:
    added = sum(1 for row in rows if row.kind == "insert")
    removed = sum(1 for row in rows if row.kind == "delete")
    changed = sum(1 for row in rows if row.kind == "replace")
    formatting = sum(1 for row in rows if row.format_changes)

    left_chars = sum(len(line.text) for line in left)
    right_chars = sum(len(line.text) for line in right)
    total = left_chars + right_chars

    # Matched characters, counting equal rows twice and the unchanged parts of
    # refined rows: four changed numbers in a contract should not read as a
    # 30% similar document.
    matched = 0
    for row in rows:
        if row.kind == "equal" and row.left and row.right:
            matched += len(row.left.text) + len(row.right.text)
        elif row.kind == "replace" and row.left_inline and row.right_inline:
            matched += sum(len(s.text) for s in row.left_inline if s.kind == "equal")
            matched += sum(len(s.text) for s in row.right_inline if s.kind == "equal")

    similarity = min(matched / total, 1.0) if total else 1.0

    return Stats(
        left_lines=len(left),
        right_lines=len(right),
        added=added,
        removed=removed,
        changed=changed,
        similarity=similarity,
        formatting=formatting,
    )


def _is_change(row: Row) -> bool:
    return row.kind != "equal" or bool(row.format_changes)


def fold_equal_runs(rows: Sequence[Row], context: int) -> list[Row]:
    """Replace long runs of identical rows with a gap marker.

    ``context`` rows are kept before and after every change. The first row
    after a gap carries ``hidden_before``; a gap at the very end is a
    placeholder row with no lines.
    """
    keep = max(context, 0)
    out: list[Row] = []
    index = 0
    total = len(rows)
    while index < total:
        if _is_change(rows[index]):
            out.append(rows[index])
            index += 1
            continue
        end = index
        while end < total and not _is_change(rows[end]):
            end += 1
        run = list(rows[index:end])
        at_start = index == 0
        at_end = end == total
        head = 0 if at_start else keep
        tail = 0 if at_end else keep
        if len(run) <= head + tail + 1:
            out.extend(run)
        else:
            out.extend(run[:head])
            hidden = len(run) - head - tail
            if tail:
                following = run[len(run) - tail]
                following.hidden_before = hidden
                out.append(following)
                out.extend(run[len(run) - tail + 1 :])
            else:
                out.append(Row(kind="equal", hidden_before=hidden))
        index = end
    return out


# Backwards-compatible private name.
_fold_equal_runs = fold_equal_runs


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
