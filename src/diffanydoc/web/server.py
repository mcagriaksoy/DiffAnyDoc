"""Local HTTP API and web UI (FastAPI + static SPA).

The UI talks only to this API, so a React/Electron shell can replace the
frontend later without touching the engine.
"""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..core import ocr
from ..core.adapters import AdapterError, supported_extensions
from ..core.diff import DiffOptions, change_rects, compare_documents
from ..core.model import DiffResult, Document, VisualPage
from ..core.render import render_png
from ..core.report.html import render_html
from ..core.report.json import result_to_dict, visual_page_to_dict
from ..i18n import available_languages, resolve_language, strings
from ..system import accent_color

# FastAPI is an optional extra (``pip install 'diffanydoc[web]'``). Importing
# this module without it raises ImportError, which the CLI turns into a hint.
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
MAX_COMPARISONS = 16
_OCR_MODES = ("auto", "off", "force")


@dataclass
class Comparison:
    id: str
    directory: Path
    left: Path
    right: Path
    result: DiffResult
    payload: dict[str, Any]
    left_doc: Document | None = None
    right_doc: Document | None = None
    visual: dict[int, VisualPage] = field(default_factory=dict)
    overlays: dict[int, bytes] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    created: datetime = field(default_factory=datetime.now)


_COMPARISONS: "OrderedDict[str, Comparison]" = OrderedDict()
_REGISTRY_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Application factory
# --------------------------------------------------------------------------- #


def create_app() -> FastAPI:
    app = FastAPI(
        title="DiffAnyDoc",
        version=__version__,
        description="Compare documents side by side.",
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(AdapterError)
    async def adapter_error(_request: Any, exc: AdapterError) -> JSONResponse:
        # A file we cannot read is the user's input, not a server failure.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.get("/api/formats")
    def formats() -> dict[str, Any]:
        return {"extensions": supported_extensions()}

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "version": __version__,
            "extensions": supported_extensions(),
            "ocr": ocr.status(),
        }

    @app.get("/api/system/theme")
    def system_theme() -> dict[str, Any]:
        return {"accent": accent_color(), "platform": sys.platform}

    @app.get("/api/updates")
    def updates() -> dict[str, Any]:
        from ..updates import check

        return check().as_dict()

    @app.get("/api/i18n/languages")
    def languages() -> dict[str, Any]:
        return {
            "languages": available_languages(),
            "default": resolve_language(None),
        }

    @app.get("/api/i18n/{language}")
    def i18n_catalog(language: str) -> dict[str, Any]:
        lang = resolve_language(language)
        return {"language": lang, "strings": strings(lang)}

    @app.post("/api/compare")
    async def compare_uploads(
        left: UploadFile = File(...),
        right: UploadFile = File(...),
        context: int = Form(3),
        case_sensitive: bool = Form(True),
        collapse_whitespace: bool = Form(True),
        fold_equal: bool = Form(False),
        reflow: bool = Form(True),
        compare_formatting: bool = Form(False),
        ocr_mode: str = Form("auto"),
        ocr_lang: str | None = Form(None),
    ) -> JSONResponse:
        directory = Path(tempfile.mkdtemp(prefix="diffanydoc-"))
        try:
            left_path = _store_upload(left, directory, "left")
            right_path = _store_upload(right, directory, "right")
            options = _options(
                context=context,
                case_sensitive=case_sensitive,
                collapse_whitespace=collapse_whitespace,
                fold_equal=fold_equal,
                reflow=reflow,
                compare_formatting=compare_formatting,
                ocr=ocr_mode,
                ocr_lang=ocr_lang,
            )
            comparison = await run_in_threadpool(
                _run_compare, left_path, right_path, directory, options
            )
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return JSONResponse(comparison.payload)

    @app.post("/api/compare-paths")
    def compare_paths(body: dict[str, Any]) -> JSONResponse:
        left_path = Path(str(body.get("left", ""))).expanduser()
        right_path = Path(str(body.get("right", ""))).expanduser()
        if not left_path.is_file() or not right_path.is_file():
            raise HTTPException(status_code=400, detail="both files must exist")
        options = _options(
            context=int(body.get("context", 3)),
            case_sensitive=bool(body.get("case_sensitive", True)),
            collapse_whitespace=bool(body.get("collapse_whitespace", True)),
            fold_equal=bool(body.get("fold_equal", False)),
            reflow=bool(body.get("reflow", True)),
            compare_formatting=bool(body.get("compare_formatting", False)),
            ocr=str(body.get("ocr", "auto")),
            ocr_lang=body.get("ocr_lang") or None,
        )
        comparison = _run_compare(left_path, right_path, None, options)
        return JSONResponse(comparison.payload)

    @app.get("/api/compare/{comparison_id}")
    def get_comparison(comparison_id: str) -> JSONResponse:
        return JSONResponse(_get(comparison_id).payload)

    @app.get("/api/compare/{comparison_id}/report", response_class=HTMLResponse)
    def get_report(comparison_id: str, lang: str | None = None) -> HTMLResponse:
        comparison = _get(comparison_id)
        _ensure_visual(comparison)
        return HTMLResponse(render_html(comparison.result, language=lang))

    @app.get("/api/compare/{comparison_id}/visual")
    def get_visual(comparison_id: str, pair: int | None = None) -> JSONResponse:
        comparison = _get(comparison_id)
        pages = _ensure_visual(comparison, None if pair is None else [pair])
        return JSONResponse(
            {
                "pages": [visual_page_to_dict(page) for page in pages],
                "regions": sum(len(page.regions) for page in pages),
            }
        )

    @app.get("/api/compare/{comparison_id}/overlay/{pair}.png")
    def get_overlay(comparison_id: str, pair: int) -> Response:
        comparison = _get(comparison_id)
        data = _overlay(comparison, pair)
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/compare/{comparison_id}/page/{side}/{index}.png")
    def get_page(comparison_id: str, side: str, index: int, dpi: int = 110) -> Response:
        comparison = _get(comparison_id)
        if side not in ("left", "right"):
            raise HTTPException(status_code=404, detail="invalid side")
        document = comparison.left_doc if side == "left" else comparison.right_doc
        if document is None or not document.renderable:
            raise HTTPException(status_code=404, detail="this file cannot be rendered as pages")
        if index < 0 or index >= document.page_count:
            raise HTTPException(status_code=404, detail="page not found")
        # Image pages are in pixels; 72 "dpi" is their native size.
        resolution = 72 if document.kind == "image" else max(60, min(dpi, 300))
        try:
            data = render_png(document, index, resolution)
        except Exception as exc:  # pragma: no cover - renderer specific
            raise HTTPException(status_code=500, detail=f"render failed: {exc}") from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    return app


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _options(**values: Any) -> DiffOptions:
    if values.get("ocr") not in _OCR_MODES:
        values["ocr"] = "auto"
    lang = values.get("ocr_lang")
    if lang is not None and not all(part.isalnum() or part == "_" for part in str(lang).split("+")):
        raise HTTPException(status_code=400, detail="invalid OCR language")
    return DiffOptions(**values)


def _store_upload(upload: Any, directory: Path, fallback: str) -> Path:
    name = Path(upload.filename or fallback).name or fallback
    target = directory / name
    if target.exists():
        target = directory / f"{fallback}-{name}"
    with target.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return target


def _run_compare(
    left_path: Path,
    right_path: Path,
    directory: Path | None,
    options: DiffOptions,
) -> Comparison:
    result, left_doc, right_doc = compare_documents(left_path, right_path, options)

    comparison = Comparison(
        id=uuid.uuid4().hex,
        directory=directory or Path(tempfile.gettempdir()),
        left=left_path,
        right=right_path,
        result=result,
        payload={},
        left_doc=left_doc,
        right_doc=right_doc,
    )
    if result.visual is not None:
        comparison.visual = {page.pair: page for page in result.visual}
    comparison.payload = _payload(comparison)
    # Path comparisons (desktop shell) are remembered too, so the report link
    # and the PDF page images keep working for the lifetime of the server.
    _remember(comparison)
    return comparison


def _payload(comparison: Comparison) -> dict[str, Any]:
    result = comparison.result
    payload = result_to_dict(result)
    payload["id"] = comparison.id
    payload["pages"] = {
        "left": result.left_info.pages if result.left_info else [],
        "right": result.right_info.pages if result.right_info else [],
    }
    payload["renderable"] = {
        "left": bool(result.left_info and result.left_info.renderable),
        "right": bool(result.right_info and result.right_info.renderable),
    }
    payload["rects"] = change_rects(result)
    return payload


def _ensure_visual(comparison: Comparison, pairs: list[int] | None = None) -> list[VisualPage]:
    """Compute (and cache) the visual comparison for some or all page pairs."""
    result = comparison.result
    if not (result.left_info and result.left_info.renderable) or not (
        result.right_info and result.right_info.renderable
    ):
        return []
    if comparison.left_doc is None or comparison.right_doc is None:
        return []
    from ..core.visual import VisualOptions, compare_pair, overlay_image

    wanted = range(len(result.page_map)) if pairs is None else pairs
    options = VisualOptions(
        dpi=int(result.options.get("visual_dpi", 100)),
        tolerance=int(result.options.get("visual_tolerance", 40)),
    )
    pages: list[VisualPage] = []
    with comparison.lock:
        for index in wanted:
            if index < 0 or index >= len(result.page_map):
                raise HTTPException(status_code=404, detail="page pair not found")
            page = comparison.visual.get(index)
            if page is None:
                page, diff = compare_pair(
                    comparison.left_doc,
                    comparison.right_doc,
                    index,
                    result.page_map[index],
                    options,
                )
                comparison.visual[index] = page
                if diff is not None and index not in comparison.overlays:
                    comparison.overlays[index] = _png(overlay_image(diff))
            pages.append(page)
        if len(comparison.visual) == len(result.page_map) and result.visual is None:
            result.visual = [comparison.visual[i] for i in range(len(result.page_map))]
            result.stats.visual_regions = sum(len(p.regions) for p in result.visual)
    return pages


def _overlay(comparison: Comparison, pair: int) -> bytes:
    cached = comparison.overlays.get(pair)
    if cached is not None:
        return cached
    result = comparison.result
    if pair < 0 or pair >= len(result.page_map):
        raise HTTPException(status_code=404, detail="page pair not found")
    page_pair = result.page_map[pair]
    if page_pair.left is None or page_pair.right is None:
        raise HTTPException(status_code=404, detail="the page exists on one side only")
    if comparison.left_doc is None or comparison.right_doc is None or not (
        comparison.left_doc.renderable and comparison.right_doc.renderable
    ):
        raise HTTPException(status_code=404, detail="these files cannot be rendered as pages")
    from ..core.visual import VisualOptions, compare_pair, overlay_image

    with comparison.lock:
        page, diff = compare_pair(
            comparison.left_doc,
            comparison.right_doc,
            pair,
            page_pair,
            VisualOptions(dpi=int(result.options.get("visual_dpi", 100))),
        )
        comparison.visual.setdefault(pair, page)
        data = _png(overlay_image(diff)) if diff is not None else b""
        comparison.overlays[pair] = data
    return data


def _png(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _remember(comparison: Comparison) -> None:
    with _REGISTRY_LOCK:
        _COMPARISONS[comparison.id] = comparison
        _COMPARISONS.move_to_end(comparison.id)
        while len(_COMPARISONS) > MAX_COMPARISONS:
            _, expired = _COMPARISONS.popitem(last=False)
            if expired.directory.name.startswith("diffanydoc-"):
                shutil.rmtree(expired.directory, ignore_errors=True)


def _get(comparison_id: str) -> Comparison:
    comparison = _COMPARISONS.get(comparison_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="comparison not found")
    return comparison


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def run(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    import uvicorn

    if reload:
        uvicorn.run(
            "diffanydoc.web.server:app", host=host, port=port, reload=True, ws="none"
        )
    else:
        uvicorn.run(create_app(), host=host, port=port, ws="none")


app = create_app()
