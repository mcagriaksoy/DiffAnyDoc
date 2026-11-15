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
from ..model import DiffResult, Document, Line, OcrStats, PagePair, Row, Segment, Stats, VisualDiff
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
    #: Comparison mode: "strict" (layout/order-aware) or "text_only" (content-only, order-independent).
    compare_mode: str = "strict"
    #: Numeric difference tolerance: numbers differing by <= this amount are treated as equal.
    numeric_tolerance: float | None = None
    #: Skip repeating headers, footers, and page numbers in top/bottom 7% bands.
    ignore_headers_footers: bool = False


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
            stats=Stats(
                left_lines=0,
                right_lines=0,
                similarity=1.0,
            ),
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

    is_text_only = options.compare_mode == "text_only"
    left_lines = document_lines(
        left_doc,
        case_sensitive=False if is_text_only else options.case_sensitive,
        collapse_whitespace=True if is_text_only else options.collapse_whitespace,
        compare_formatting=False if is_text_only else options.compare_formatting,
        reflow=True if is_text_only else options.reflow,
        ignore_headers_footers=options.ignore_headers_footers,
    )
    right_lines = document_lines(
        right_doc,
        case_sensitive=False if is_text_only else options.case_sensitive,
        collapse_whitespace=True if is_text_only else options.collapse_whitespace,
        compare_formatting=False if is_text_only else options.compare_formatting,
        reflow=True if is_text_only else options.reflow,
        ignore_headers_footers=options.ignore_headers_footers,
    )

    has_real_geometry = (
        left_doc.kind in ("pdf", "image") and right_doc.kind in ("pdf", "image")
    )
    if has_real_geometry:
        left_lines, right_lines = _reconcile_split_lines(
            left_lines,
            right_lines,
            case_sensitive=False if is_text_only else options.case_sensitive,
            collapse_whitespace=True if is_text_only else options.collapse_whitespace,
        )

    rows = _build_rows(left_lines, right_lines, options)
    _mark_moved_rows(rows)
    if is_text_only or has_real_geometry:
        rows = _collapse_moved_to_equal(
            rows,
            pair_fuzzy=has_real_geometry and not is_text_only,
            tolerance=options.numeric_tolerance,
        )
    _detect_position_shifts(rows, options, has_real_geometry=has_real_geometry)
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


def _reconcile_split_lines(
    left: list[Line],
    right: list[Line],
    *,
    case_sensitive: bool,
    collapse_whitespace: bool,
) -> tuple[list[Line], list[Line]]:
    """Reconcile lines that were horizontally grouped or wrapped differently across two PDFs.

    1. Horizontal gap splitting: if a line on side A has wide horizontal gaps
       between spans (>= 18pt, e.g. two columns/boxes at the same Y coordinate)
       and splitting at those gaps yields pieces that match lines on side B,
       split the line into independent ``Line`` objects with their own ``bbox``.
    2. Wrapped line joining: if 2-3 consecutive unmatched lines on side A equal
       a single line on side B when joined, merge them into one ``Line``.
    """
    from ..layout import union
    from ..model import Span
    from ..normalize import normalize_line

    def _norm(txt: str) -> str:
        return normalize_line(
            txt,
            case_sensitive=case_sensitive,
            collapse_whitespace=collapse_whitespace,
        ).strip().casefold()

    def _split_wide_gaps(lines: list[Line], other_norms: set[str]) -> list[Line]:
        out: list[Line] = []
        for line in lines:
            if (
                line.cells is not None
                or len(line.spans) < 2
                or _norm(line.text) in other_norms
            ):
                out.append(line)
                continue
            groups: list[list[Span]] = [[line.spans[0]]]
            for prev_s, cur_s in zip(line.spans, line.spans[1:]):
                if cur_s.page == prev_s.page and (cur_s.bbox[0] - prev_s.bbox[2]) >= 18.0:
                    groups.append([cur_s])
                else:
                    groups[-1].append(cur_s)
            if len(groups) < 2:
                out.append(line)
                continue
            pieces: list[tuple[str, list[Span], Any]] = []
            matched_any = False
            for grp in groups:
                s0 = grp[0].start
                s1 = grp[-1].end
                sub_text = line.text[s0:s1].strip()
                if not sub_text:
                    continue
                shift = s0 + (len(line.text[s0:s1]) - len(line.text[s0:s1].lstrip()))
                sub_spans = [
                    Span(
                        max(0, sp.start - shift),
                        max(0, sp.end - shift),
                        sp.page,
                        sp.bbox,
                    )
                    for sp in grp
                ]
                sub_bbox = union(sp.bbox for sp in grp)
                if _norm(sub_text) in other_norms:
                    matched_any = True
                pieces.append((sub_text, sub_spans, sub_bbox))
            if matched_any and len(pieces) >= 2:
                for sub_text, sub_spans, sub_bbox in pieces:
                    out.append(
                        Line(
                            number=line.number,
                            page=line.page,
                            text=sub_text,
                            norm=normalize_line(
                                sub_text,
                                case_sensitive=case_sensitive,
                                collapse_whitespace=collapse_whitespace,
                            ),
                            bbox=sub_bbox,
                            spans=sub_spans,
                            style=dict(line.style) if line.style else {},
                            cells=None,
                        )
                    )
            else:
                out.append(line)
        for idx, item in enumerate(out, start=1):
            item.number = idx
        return out

    right_norm_set = {_norm(l.text) for l in right if _norm(l.text)}
    left = _split_wide_gaps(left, right_norm_set)
    left_norm_set = {_norm(l.text) for l in left if _norm(l.text)}
    right = _split_wide_gaps(right, left_norm_set)

    def _merge_wrapped(lines: list[Line], other_norms: set[str], own_norms: set[str]) -> list[Line]:
        out: list[Line] = []
        i = 0
        n = len(lines)
        while i < n:
            cur = lines[i]
            cur_k = _norm(cur.text)
            if cur.cells is None and cur_k not in other_norms and i + 1 < n:
                merged_done = False
                for span_cnt in (2, 3):
                    if i + span_cnt > n:
                        continue
                    chunk = lines[i : i + span_cnt]
                    if any(
                        c.cells is not None
                        or c.page != cur.page
                        or (_norm(c.text) in other_norms and _norm(c.text) in own_norms)
                        for c in chunk
                    ):
                        continue
                    joined_text = " ".join(c.text.strip() for c in chunk if c.text.strip())
                    if _norm(joined_text) in other_norms:
                        new_spans: list[Span] = []
                        parts: list[str] = []
                        offset = 0
                        for c in chunk:
                            t_part = c.text.strip()
                            if not t_part:
                                continue
                            if parts:
                                parts.append(" ")
                                offset += 1
                            for sp in c.spans:
                                new_spans.append(
                                    Span(sp.start + offset, sp.end + offset, sp.page, sp.bbox)
                                )
                            parts.append(t_part)
                            offset += len(t_part)
                        full_text = "".join(parts)
                        out.append(
                            Line(
                                number=cur.number,
                                page=cur.page,
                                text=full_text,
                                norm=normalize_line(
                                    full_text,
                                    case_sensitive=case_sensitive,
                                    collapse_whitespace=collapse_whitespace,
                                ),
                                bbox=union(c.bbox for c in chunk if c.bbox is not None),
                                spans=new_spans,
                                style=dict(cur.style) if cur.style else {},
                                cells=None,
                            )
                        )
                        i += span_cnt
                        merged_done = True
                        break
                if merged_done:
                    continue
            out.append(cur)
            i += 1
        for idx, item in enumerate(out, start=1):
            item.number = idx
        return out

    right_norm_set = {_norm(l.text) for l in right if _norm(l.text)}
    left_norm_set = {_norm(l.text) for l in left if _norm(l.text)}
    left = _merge_wrapped(left, right_norm_set, left_norm_set)
    left_norm_set = {_norm(l.text) for l in left if _norm(l.text)}
    right = _merge_wrapped(right, left_norm_set, right_norm_set)
    return left, right


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
    opcodes = matcher.get_opcodes()
    unmatched_left: set[str] = set()
    unmatched_right: set[str] = set()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        for a in left[i1:i2]:
            k = a.norm.strip().casefold()
            if len(k) >= 2:
                unmatched_left.add(k)
        for b in right[j1:j2]:
            k = b.norm.strip().casefold()
            if len(k) >= 2:
                unmatched_right.add(k)
    exact_moved_keys = unmatched_left & unmatched_right

    rows: list[Row] = []
    for tag, i1, i2, j1, j2 in opcodes:
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
                exact_moved_keys=exact_moved_keys,
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
    exact_moved_keys: set[str] | None = None,
) -> list[Row]:
    """Pair up changed lines so a rewrite does not look like delete+insert.

    A small look-ahead decides which side owns an unmatched line, which is what
    makes side-by-side views readable. Lines whose exact text appears elsewhere
    as a moved block are preserved as single rows so move-pairing can match them.
    """
    rows: list[Row] = []
    if len(left) * len(right) > 25_000:
        for a, b in zip(left, right):
            rows.append(_replace_row(a, b, tolerance=tolerance))
        if len(left) > len(right):
            rows.extend(_single_row(a, None, "delete") for a in left[len(right) :])
        elif len(right) > len(left):
            rows.extend(_single_row(None, b, "insert") for b in right[len(left) :])
        return rows
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        if exact_moved_keys:
            ka = a.norm.strip().casefold()
            kb = b.norm.strip().casefold()
            if ka != kb:
                if ka in exact_moved_keys and kb not in exact_moved_keys:
                    rows.append(_single_row(a, None, "delete"))
                    i += 1
                    continue
                if kb in exact_moved_keys and ka not in exact_moved_keys:
                    rows.append(_single_row(None, b, "insert"))
                    j += 1
                    continue
                if ka in exact_moved_keys and kb in exact_moved_keys:
                    rows.append(_single_row(a, None, "delete"))
                    rows.append(_single_row(None, b, "insert"))
                    i += 1
                    j += 1
                    continue
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
    left_words = sum(len(line.text.split()) for line in left)
    right_words = sum(len(line.text.split()) for line in right)

    left_reading_time = left_words / 200.0
    right_reading_time = right_words / 200.0

    words_added = 0
    words_removed = 0
    for row in rows:
        if row.kind == "insert" and row.right:
            words_added += len(row.right.text.split())
        elif row.kind == "delete" and row.left:
            words_removed += len(row.left.text.split())
        elif row.kind == "replace":
            if row.right_inline:
                words_added += sum(len(s.text.split()) for s in row.right_inline if s.kind == "insert")
            if row.left_inline:
                words_removed += sum(len(s.text.split()) for s in row.left_inline if s.kind == "delete")

    words_changed = words_added + words_removed
    tot_words = max(left_words + right_words, 1)
    change_density = min(words_changed / tot_words, 1.0)

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
        left_words=left_words,
        right_words=right_words,
        left_chars=left_chars,
        right_chars=right_chars,
        left_reading_time_min=left_reading_time,
        right_reading_time_min=right_reading_time,
        words_added=words_added,
        words_removed=words_removed,
        words_changed=words_changed,
        change_density=change_density,
    )


def _is_change(row: Row) -> bool:
    return row.kind != "equal" or bool(getattr(row, "format_changes", None))


_MIN_MOVE_LEN = 4


def _mark_moved_rows(rows: list[Row]) -> None:
    """Flag deleted/inserted rows whose text appears identically or similarly on the other side."""
    from difflib import SequenceMatcher
    import re

    inserts_by_text: dict[str, list[Row]] = {}
    unmatched_inserts: list[Row] = []
    for row in rows:
        if row.kind == "insert" and row.right is not None:
            key = row.right.norm.strip().casefold()
            if len(key) >= _MIN_MOVE_LEN:
                inserts_by_text.setdefault(key, []).append(row)

    next_move_id = 1
    unmatched_deletes: list[Row] = []
    for row in rows:
        if row.kind == "delete" and row.left is not None:
            key = row.left.norm.strip().casefold()
            if len(key) >= _MIN_MOVE_LEN:
                bucket = inserts_by_text.get(key)
                if bucket:
                    partner = bucket.pop(0)
                    row.moved = True
                    partner.moved = True
                    row.move_id = next_move_id
                    partner.move_id = next_move_id
                    next_move_id += 1
                else:
                    unmatched_deletes.append(row)

    for bucket in inserts_by_text.values():
        unmatched_inserts.extend(bucket)

    if not unmatched_deletes or not unmatched_inserts:
        return
    if len(unmatched_deletes) * len(unmatched_inserts) > 15_000:
        return

    def _tokens(text: str) -> set[str]:
        return {w for w in re.findall(r"\w+", text.casefold()) if len(w) >= 3}

    candidates: list[tuple[float, int, int]] = []
    ins_tokens = [
        (_tokens(r.right.norm), r.right.norm.strip().casefold())
        for r in unmatched_inserts
        if r.right is not None
    ]
    for di, d_row in enumerate(unmatched_deletes):
        assert d_row.left is not None
        d_norm = d_row.left.norm.strip().casefold()
        d_toks = _tokens(d_norm)
        if not d_toks or len(d_norm) < 6:
            continue
        for ii, (i_toks, i_norm) in enumerate(ins_tokens):
            if not i_toks or len(i_norm) < 6:
                continue
            shared = d_toks & i_toks
            if not any(len(w) >= 4 for w in shared):
                continue
            jaccard = len(shared) / len(d_toks | i_toks)
            if jaccard >= 0.50:
                score = jaccard
            else:
                matcher = SequenceMatcher(None, d_norm, i_norm)
                if matcher.quick_ratio() < 0.50:
                    continue
                seq_ratio = matcher.ratio()
                score = max(jaccard, seq_ratio)
            if score >= 0.50:
                candidates.append((score, di, ii))

    candidates.sort(key=lambda item: item[0], reverse=True)
    used_d: set[int] = set()
    used_i: set[int] = set()
    for _score, di, ii in candidates:
        if di in used_d or ii in used_i:
            continue
        used_d.add(di)
        used_i.add(ii)
        d_row = unmatched_deletes[di]
        i_row = unmatched_inserts[ii]
        d_row.moved = True
        i_row.moved = True
        d_row.move_id = next_move_id
        i_row.move_id = next_move_id
        next_move_id += 1


def _collapse_moved_to_equal(
    rows: list[Row],
    *,
    pair_fuzzy: bool = False,
    tolerance: float | None = None,
) -> list[Row]:
    """Pair moved delete/insert rows into a single side-by-side Row.

    Exact normalized matches become ``kind="equal"`` (with ``moved=True`` so
    position shift detection can still number and draw arrows for them on PDFs).
    When ``pair_fuzzy`` is True (PDF/image layout comparison), fuzzy-matched
    moved blocks sharing a ``move_id`` are also paired side-by-side.
    """
    inserts_by_text: dict[str, list[Row]] = {}
    inserts_by_move_id: dict[int, Row] = {}
    for row in rows:
        if row.kind == "insert" and row.right is not None:
            key = row.right.norm.strip().casefold()
            if key:
                inserts_by_text.setdefault(key, []).append(row)
            if row.moved and row.move_id:
                inserts_by_move_id[row.move_id] = row

    consumed_inserts: set[int] = set()
    paired_by_delete: dict[int, Row] = {}

    for row in rows:
        if row.kind != "delete" or row.left is None:
            continue
        key = row.left.norm.strip().casefold()
        bucket = inserts_by_text.get(key) if key else None
        partner: Row | None = None
        while bucket:
            cand = bucket.pop(0)
            if id(cand) not in consumed_inserts:
                partner = cand
                break
        if partner is not None and partner.right is not None:
            consumed_inserts.add(id(partner))
            paired_by_delete[id(row)] = Row(
                kind="equal",
                left=row.left,
                right=partner.right,
                moved=True,
                move_id=row.move_id or partner.move_id or 1,
            )
            continue
        if pair_fuzzy and row.moved and row.move_id:
            fuzzy_partner = inserts_by_move_id.get(row.move_id)
            if (
                fuzzy_partner is not None
                and id(fuzzy_partner) not in consumed_inserts
                and fuzzy_partner.right is not None
            ):
                consumed_inserts.add(id(fuzzy_partner))
                rep = _replace_row(row.left, fuzzy_partner.right, tolerance=tolerance)
                rep.moved = True
                rep.move_id = row.move_id
                paired_by_delete[id(row)] = rep

    out: list[Row] = []
    for row in rows:
        if id(row) in consumed_inserts:
            continue
        if id(row) in paired_by_delete:
            out.append(paired_by_delete[id(row)])
            continue
        out.append(row)
    return out


_SHIFT_THRESHOLD_PT = 4.5


def _format_shift_label(dx: float, dy: float, *, reordered: bool = False) -> str:
    parts: list[str] = []
    if abs(dx) >= _SHIFT_THRESHOLD_PT:
        arrow = "→" if dx > 0 else "←"
        parts.append(f"{arrow} Δx {dx:+.0f}pt")
    if abs(dy) >= _SHIFT_THRESHOLD_PT:
        arrow = "↓" if dy > 0 else "↑"
        parts.append(f"{arrow} Δy {dy:+.0f}pt")
    if not parts and reordered:
        parts.append(f"↕ Δy {dy:+.0f}pt")
    return " · ".join(parts) if parts else f"Δx {dx:+.0f}pt"


def _detect_position_shifts(
    rows: list[Row],
    options: DiffOptions,
    *,
    has_real_geometry: bool,
) -> None:
    """Detect and sequentially number (1, 2, 3...) matched blocks whose position shifted.

    In ``strict`` (Visual & Position) mode, lines whose text is identical but
    whose bounding box shifted or reordered on the page are numbered ``#1, #2, #3...``
    and flagged with ``position_shift`` metadata (including both left & right
    bounding boxes so the UI can draw numbered badges and connecting arrows).
    In ``text_only`` (Ignore Layout Shifts) mode, they remain ``kind="equal"``
    (0 changes, 100% similarity).
    """
    if not has_real_geometry:
        return
    is_text_only = options.compare_mode == "text_only"
    prev_bottom: dict[tuple[int, int], tuple[float, float]] = {}
    shift_seq = 0
    block_seq = 0

    for row in rows:
        a = row.left
        b = row.right
        if a is None or b is None or a.bbox is None or b.bbox is None:
            continue
        block_seq += 1
        was_reordered = bool(row.moved)
        page_key = (a.page, b.page)
        dx = b.bbox[0] - a.bbox[0]
        raw_dy = b.bbox[1] - a.bbox[1]
        if page_key in prev_bottom:
            prev_a_bot, prev_b_bot = prev_bottom[page_key]
            eff_dy = (b.bbox[1] - prev_b_bot) - (a.bbox[1] - prev_a_bot)
        else:
            eff_dy = raw_dy
        prev_bottom[page_key] = (a.bbox[3], b.bbox[3])

        if abs(dx) < _SHIFT_THRESHOLD_PT and a.spans and b.spans and len(a.spans) == len(b.spans):
            best_span_dx = 0.0
            for sa, sb in zip(a.spans, b.spans):
                sdx = sb.bbox[0] - sa.bbox[0]
                if abs(sdx) > abs(best_span_dx):
                    best_span_dx = sdx
            if abs(best_span_dx) >= _SHIFT_THRESHOLD_PT:
                dx = best_span_dx

        is_shifted = (
            abs(dx) >= _SHIFT_THRESHOLD_PT
            or abs(eff_dy) >= _SHIFT_THRESHOLD_PT
            or (was_reordered and abs(raw_dy) >= _SHIFT_THRESHOLD_PT)
            or (a.page != b.page)
        )
        if not is_shifted:
            if is_text_only:
                row.moved = False
                row.move_id = 0
            continue

        shift_seq += 1
        row.move_id = shift_seq
        dy_for_label = (
            raw_dy
            if (abs(eff_dy) >= _SHIFT_THRESHOLD_PT or was_reordered or a.page != b.page)
            else 0.0
        )
        label = _format_shift_label(dx, dy_for_label, reordered=was_reordered)
        shift_meta = {
            "id": shift_seq,
            "block_num": block_seq,
            "dx": round(dx, 1),
            "dy": round(raw_dy, 1),
            "eff_dy": round(eff_dy, 1),
            "reordered": was_reordered,
            "left_bbox": [round(v, 2) for v in a.bbox],
            "right_bbox": [round(v, 2) for v in b.bbox],
            "left_page": a.page,
            "right_page": b.page,
            "label": label,
        }
        a.style = {**(a.style or {}), "position_shift": shift_meta}
        b.style = {**(b.style or {}), "position_shift": shift_meta}

        if row.kind == "equal":
            if not is_text_only:
                row.kind = "replace"
                row.moved = True
                if label not in row.format_changes:
                    row.format_changes.append(label)
                a.style["style_change"] = label
                a.style["summary"] = label
                b.style["style_change"] = label
                b.style["summary"] = label
                row.left_inline = [Segment(kind="equal", text=a.text)]
                row.right_inline = [Segment(kind="equal", text=b.text)]
            else:
                row.moved = False


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
