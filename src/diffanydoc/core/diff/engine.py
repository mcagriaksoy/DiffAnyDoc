"""The comparison engine: line alignment, inline refinement, statistics."""

from __future__ import annotations

from collections import OrderedDict
import copy
import hashlib
import threading
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Sequence

from ..adapters import adapter_for, adapters, load
from ..model import DiffResult, Document, Line, OcrStats, PagePair, Row, Stats, VisualDiff
from ..ocr import OcrOptions, apply_ocr
from ..visual import VisualOptions, compare_pdf_pages
from .align import align_pages
from .lines import cell_diff, document_lines, inline_diff, line_similarity, style_summary


@dataclass(slots=True)
class DiffOptions:
    #: Identical rows kept on each side of a change.
    context: int = 3
    case_sensitive: bool = True
    collapse_whitespace: bool = True
    #: Also flag lines where text is identical but font/bold/italic/size changed.
    compare_formatting: bool = False
    #: Minimum similarity for two changed lines to be shown side by side.
    pair_threshold: float = 0.4
    #: Fold long unchanged runs (HTML report). The API asks for full rows.
    fold_equal: bool = True
    #: Join the visual lines of a paragraph before comparing (PDF/OCR).
    reflow: bool = True
    #: Fast-check SHA-256 checksums before parsing; skip loading if identical.
    fast_check: bool = True
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
    #: Numeric difference tolerance: numbers differing by <= this amount are treated as equal.
    numeric_tolerance: float | None = None


def file_sha256(path: str | Path) -> str:
    """Compute SHA-256 hex digest of a file on disk."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(target)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_PRELOAD_LOCK = threading.Lock()
_PRELOAD_CACHE: "OrderedDict[str, Document]" = OrderedDict()
_MAX_PRELOAD_ITEMS = 12


def preload_document(
    path: str | Path,
    ocr: bool = False,
    ocr_language: str = "eng",
    ocr_dpi: int = 300,
    ocr_min_chars: int = 8,
    ocr_max_pages: int = 60,
    ocr_cache_dir: str | None = None,
) -> tuple[str, Document, OcrStats | None]:
    """Parse (and optionally OCR) a single file ahead of time, caching by SHA-256."""
    target = Path(path).expanduser()
    digest = file_sha256(target)
    with _PRELOAD_LOCK:
        cached_doc = _PRELOAD_CACHE.get(digest)
        if cached_doc is not None:
            _PRELOAD_CACHE.move_to_end(digest)
            document = copy.deepcopy(cached_doc)
            document.path = target
        else:
            document = None

    if document is None:
        document = load(target)
        with _PRELOAD_LOCK:
            _PRELOAD_CACHE[digest] = copy.deepcopy(document)
            _PRELOAD_CACHE.move_to_end(digest)
            while len(_PRELOAD_CACHE) > _MAX_PRELOAD_ITEMS:
                _PRELOAD_CACHE.popitem(last=False)

    ocr_stats: OcrStats | None = None
    if ocr:
        ocr_options = OcrOptions(
            language=ocr_language,
            dpi=ocr_dpi,
            min_text_chars=ocr_min_chars,
            max_pages=ocr_max_pages,
            cache_dir=ocr_cache_dir,
        )
        ocr_stats = apply_ocr(document, ocr_options)

    return digest, document, ocr_stats


def _load_or_cached(
    source: str | Path | Document,
    digest: str | None,
    options: DiffOptions,
) -> tuple[Document, OcrStats | None]:
    if isinstance(source, Document):
        doc = source
    else:
        target = Path(source)
        doc = None
        if digest and options.fast_check:
            with _PRELOAD_LOCK:
                cached = _PRELOAD_CACHE.pop(digest, None)
                if cached is not None:
                    doc = copy.deepcopy(cached)
                    doc.path = target
        if doc is None:
            doc = load(target)

    ocr_stats = None
    if options.ocr:
        ocr_options = OcrOptions(
            language=options.ocr_language,
            dpi=options.ocr_dpi,
            min_text_chars=options.ocr_min_chars,
            max_pages=options.ocr_max_pages,
            cache_dir=options.ocr_cache_dir,
        )
        ocr_stats = apply_ocr(doc, ocr_options)
    return doc, ocr_stats


def _fast_byte_check(
    left: str | Path | Document,
    right: str | Path | Document,
    options: DiffOptions,
) -> tuple[bool, str | None, str | None]:
    """Check if two path inputs have identical size and SHA-256 without loading."""
    if isinstance(left, Document) or isinstance(right, Document):
        return False, None, None
    left_path = Path(left)
    right_path = Path(right)
    if not left_path.exists():
        raise FileNotFoundError(left_path)
    if not right_path.exists():
        raise FileNotFoundError(right_path)
    try:
        same_size = left_path.stat().st_size == right_path.stat().st_size
    except OSError:
        same_size = False
    left_hash = file_sha256(left_path)
    if not same_size:
        right_hash = file_sha256(right_path)
        return False, left_hash, right_hash
    if left_path.resolve() == right_path.resolve():
        return options.fast_check, left_hash, left_hash
    right_hash = file_sha256(right_path)
    return (options.fast_check and left_hash == right_hash), left_hash, right_hash


def _peek_page_dimensions(path: Path, kind: str) -> list[tuple[float, float]]:
    """Lightweight page geometry lookup for byte-identical files (no text extraction)."""
    if kind == "pdf":
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(str(path))
            try:
                return [(float(page.get_width()), float(page.get_height())) for page in doc]
            finally:
                doc.close()
        except Exception:
            return [(595.0, 842.0)]
    if kind == "image":
        try:
            from PIL import Image

            with Image.open(path) as img:
                return [(float(img.width), float(img.height))]
        except Exception:
            return [(595.0, 842.0)]
    return [(0.0, 0.0)]


def compare(
    left: str | Path | Document,
    right: str | Path | Document,
    options: DiffOptions | None = None,
) -> DiffResult:
    """Compare two files (or two already-loaded documents)."""
    options = options or DiffOptions()
    is_same_bytes, left_hash, right_hash = _fast_byte_check(left, right, options)
    if is_same_bytes and not isinstance(left, Document) and not isinstance(right, Document):
        left_path = Path(left)
        right_path = Path(right)
        left_kind = adapter_for(left_path).name
        right_kind = adapter_for(right_path).name
        dims = _peek_page_dimensions(left_path, left_kind)
        page_map = [
            PagePair(left=index, right=index, similarity=1.0)
            for index in range(len(dims))
        ]
        visual = None
        if options.visual and left_kind in ("pdf", "image") and right_kind in ("pdf", "image"):
            limit = max(options.visual_max_pages, 0)
            compared_pages = min(len(dims), limit)
            visual = VisualDiff(
                pages=[],
                compared=compared_pages,
                changed_pages=0,
                changed_pixels=0,
                total_pixels=max(1, compared_pages),
                max_shift=0.0,
                truncated=len(dims) > limit,
            )
        return DiffResult(
            left_path=left_path,
            right_path=right_path,
            left_kind=left_kind,
            right_kind=right_kind,
            rows=[],
            page_map=page_map,
            stats=Stats(similarity=1.0),
            visual=visual,
            ocr=None,
            options=asdict(options),
            byte_identical=True,
            left_sha256=left_hash,
            right_sha256=right_hash,
            left_pages=list(dims),
            right_pages=list(dims),
        )

    left_doc, left_ocr = _load_or_cached(left, left_hash, options)
    right_doc, right_ocr = _load_or_cached(right, right_hash, options)

    from ..layout import paginate_document

    left_doc = paginate_document(left_doc)
    right_doc = paginate_document(right_doc)

    ocr: OcrStats | None = None
    for page_stats in (left_ocr, right_ocr):
        if page_stats is None:
            continue
        ocr = page_stats if ocr is None else ocr.merged(page_stats)

    left_lines = document_lines(
        left_doc,
        case_sensitive=options.case_sensitive,
        collapse_whitespace=options.collapse_whitespace,
        compare_formatting=options.compare_formatting,
        reflow=options.reflow,
    )
    right_lines = document_lines(
        right_doc,
        case_sensitive=options.case_sensitive,
        collapse_whitespace=options.collapse_whitespace,
        compare_formatting=options.compare_formatting,
        reflow=options.reflow,
    )

    rows = _build_rows(left_lines, right_lines, options)
    stats = _stats(left_lines, right_lines, rows)
    if options.fold_equal or len(rows) > _AUTO_FOLD_LINE_THRESHOLD:
        rows = _fold_equal_runs(rows, max(options.context, 3))

    page_map = align_pages(left_doc, right_doc)
    visual = None
    if (
        options.visual
        and left_doc.kind in ("pdf", "image")
        and right_doc.kind in ("pdf", "image")
    ):
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
        byte_identical=bool(left_hash and left_hash == right_hash),
        left_sha256=left_hash,
        right_sha256=right_hash,
        left_pages=[(p.width or 595.0, p.height or 842.0) for p in left_doc.pages],
        right_pages=[(p.width or 595.0, p.height or 842.0) for p in right_doc.pages],
    )


def _coerce(source: str | Path | Document) -> Document:
    if isinstance(source, Document):
        return source
    return load(source)


# --------------------------------------------------------------------------- #
# Row construction
# --------------------------------------------------------------------------- #


#: Above this total line count, automatically fold long unchanged runs so the
#: browser / webview DOM does not freeze on multi-thousand-row CSV/XLSX files.
_AUTO_FOLD_LINE_THRESHOLD = 1200


def _build_rows(
    left: Sequence[Line], right: Sequence[Line], options: DiffOptions
) -> list[Row]:
    use_autojunk = (len(left) + len(right)) > 800
    matcher = SequenceMatcher(
        None,
        [line.norm for line in left],
        [line.norm for line in right],
        autojunk=use_autojunk,
    )
    rows: list[Row] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for a, b in zip(left[i1:i2], right[j1:j2]):
                if options.compare_formatting and _styles_differ(a, b):
                    rows.append(_style_replace_row(a, b))
                else:
                    rows.append(_equal_row(a, b))
            continue
        if tag == "delete":
            rows.extend(_single_row(a, None, "delete") for a in left[i1:i2])
            continue
        if tag == "insert":
            rows.extend(_single_row(None, b, "insert") for b in right[j1:j2])
            continue
        rows.extend(
            _refine_replacement(
                left[i1:i2],
                right[j1:j2],
                options.pair_threshold,
                tolerance=options.numeric_tolerance,
            )
        )
    return rows


def _styles_differ(left: Line, right: Line) -> bool:
    s_left = style_summary(left.style)
    s_right = style_summary(right.style)
    if not s_left and not s_right:
        return False
    return s_left != s_right


def _style_replace_row(left: Line, right: Line) -> Row:
    s_left = style_summary(left.style) or "plain"
    s_right = style_summary(right.style) or "plain"
    left.style = {**left.style, "style_change": f"{s_left} → {s_right}", "summary": s_left}
    right.style = {**right.style, "style_change": f"{s_left} → {s_right}", "summary": s_right}
    left_inline, right_inline = inline_diff(left.text, right.text)
    return Row(
        kind="replace",
        left=left,
        right=right,
        left_inline=left_inline,
        right_inline=right_inline,
    )


def _equal_row(left: Line, right: Line) -> Row:
    return Row(kind="equal", left=left, right=right)


def _single_row(left: Line | None, right: Line | None, kind: str) -> Row:
    return Row(kind=kind, left=left, right=right)  # type: ignore[arg-type]


def _replace_row(left: Line, right: Line, tolerance: float | None = None) -> Row:
    if left.cells is not None and right.cells is not None:
        left_inline, right_inline = cell_diff(left.cells, right.cells, tolerance=tolerance)
    else:
        left_inline, right_inline = inline_diff(left.text, right.text, tolerance=tolerance)

    if (
        tolerance is not None
        and left_inline
        and right_inline
        and all(s.kind == "equal" for s in left_inline)
        and all(s.kind == "equal" for s in right_inline)
    ):
        return Row(
            kind="equal",
            left=left,
            right=right,
            left_inline=left_inline,
            right_inline=right_inline,
        )

    return Row(
        kind="replace",
        left=left,
        right=right,
        left_inline=left_inline,
        right_inline=right_inline,
    )


def _refine_replacement(
    left: Sequence[Line],
    right: Sequence[Line],
    threshold: float,
    tolerance: float | None = None,
) -> list[Row]:
    """Pair up changed lines so a rewrite does not look like delete+insert.

    A small look-ahead decides which side owns an unmatched line, which is what
    makes side-by-side views readable.
    """
    rows: list[Row] = []
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        sim = line_similarity(a, b)
        if sim >= threshold or (len(left) == len(right) and sim >= 0.2):
            rows.append(_replace_row(a, b, tolerance=tolerance))
            i += 1
            j += 1
            continue

        ahead_left = (
            line_similarity(left[i + 1], b) if i + 1 < len(left) else -1.0
        )
        ahead_right = (
            line_similarity(a, right[j + 1]) if j + 1 < len(right) else -1.0
        )
        if ahead_left < threshold and ahead_right < threshold and sim >= 0.18:
            rows.append(_replace_row(a, b, tolerance=tolerance))
            i += 1
            j += 1
            continue
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


def _is_change(row: Row) -> bool:
    return row.kind != "equal" or bool(getattr(row, "format_changes", None))


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
