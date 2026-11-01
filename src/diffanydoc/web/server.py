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
from ..core.adapters import AdapterError, load, supported_extensions
from ..core.diff import DiffOptions, compare
from ..core.model import DiffResult
from ..core.report.html import render_html
from ..core.report.json import result_to_dict
from ..i18n import available_languages, resolve_language, strings
from ..system import accent_color

# FastAPI is an optional extra (``pip install 'diffanydoc[web]'``). Importing
# this module without it raises ImportError, which the CLI turns into a hint.
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
MAX_COMPARISONS = 16


@dataclass
class Comparison:
    id: str
    directory: Path
    left: Path
    right: Path
    result: DiffResult
    payload: dict[str, Any]
    created: datetime = field(default_factory=datetime.now)


_COMPARISONS: "OrderedDict[str, Comparison]" = OrderedDict()
_PAGE_CACHE: dict[tuple[str, int, int], bytes] = {}
#: pdfium is not safe to call from several request threads at once.
_PAGE_LOCK = threading.Lock()


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

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.get("/api/formats")
    def formats() -> dict[str, Any]:
        return {"extensions": supported_extensions()}

    @app.get("/api/system/theme")
    def system_theme() -> dict[str, Any]:
        return {"accent": accent_color(), "platform": sys.platform}

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
    ) -> JSONResponse:
        directory = Path(tempfile.mkdtemp(prefix="diffanydoc-"))
        try:
            left_path = _store_upload(left, directory, "left")
            right_path = _store_upload(right, directory, "right")
            comparison = _run_compare(
                left_path,
                right_path,
                directory,
                context,
                case_sensitive,
                fold_equal,
                collapse_whitespace,
            )
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return JSONResponse(_summary(comparison))

    @app.post("/api/compare-paths")
    async def compare_paths(body: dict[str, Any]) -> JSONResponse:
        left_path = Path(str(body.get("left", ""))).expanduser()
        right_path = Path(str(body.get("right", ""))).expanduser()
        if not left_path.is_file() or not right_path.is_file():
            raise HTTPException(status_code=400, detail="both files must exist")
        comparison = _run_compare(
            left_path,
            right_path,
            None,
            int(body.get("context", 3)),
            bool(body.get("case_sensitive", True)),
            bool(body.get("fold_equal", False)),
            bool(body.get("collapse_whitespace", True)),
        )
        return JSONResponse(_summary(comparison))

    @app.get("/api/compare/{comparison_id}")
    def get_comparison(comparison_id: str) -> JSONResponse:
        return JSONResponse(_get(comparison_id).payload)

    @app.get("/api/compare/{comparison_id}/report", response_class=HTMLResponse)
    def get_report(comparison_id: str, lang: str | None = None) -> HTMLResponse:
        return HTMLResponse(render_html(_get(comparison_id).result, language=lang))

    @app.get("/api/compare/{comparison_id}/page/{side}/{index}.png")
    def get_page(comparison_id: str, side: str, index: int, dpi: int = 110) -> Response:
        comparison = _get(comparison_id)
        if side not in ("left", "right"):
            raise HTTPException(status_code=404, detail="invalid side")
        path = comparison.left if side == "left" else comparison.right
        if path.suffix.lower() != ".pdf":
            raise HTTPException(status_code=404, detail="this file cannot be rendered as pages")
        try:
            with _PAGE_LOCK:
                data = _render_page(path, index, max(60, min(dpi, 300)))
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
    context: int,
    case_sensitive: bool,
    fold_equal: bool,
    collapse_whitespace: bool = True,
) -> Comparison:
    options = DiffOptions(
        context=context,
        case_sensitive=case_sensitive,
        fold_equal=fold_equal,
        collapse_whitespace=collapse_whitespace,
    )
    result = compare(left_path, right_path, options)
    left_doc = load(left_path)
    right_doc = load(right_path)

    payload = result_to_dict(result)
    payload["id"] = uuid.uuid4().hex if directory else None
    payload["pages"] = {
        "left": [{"width": p.width, "height": p.height} for p in left_doc.pages],
        "right": [{"width": p.width, "height": p.height} for p in right_doc.pages],
    }
    payload["renderable"] = {
        "left": left_doc.kind == "pdf",
        "right": right_doc.kind == "pdf",
    }
    payload["rects"] = _rects(result)

    comparison = Comparison(
        id=payload["id"] or uuid.uuid4().hex,
        directory=directory or Path(tempfile.gettempdir()),
        left=left_path,
        right=right_path,
        result=result,
        payload=payload,
    )
    payload["id"] = comparison.id
    # Path comparisons (desktop shell) are remembered too, so the report link
    # and the PDF page images keep working for the lifetime of the server.
    _remember(comparison)
    return comparison


def _rects(result: DiffResult) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Per-page rectangles of changed lines, for the PDF overlay."""
    rects: dict[str, dict[str, list[dict[str, Any]]]] = {"left": {}, "right": {}}
    for row in result.rows:
        if row.kind == "equal":
            continue
        for side in ("left", "right"):
            line = row.left if side == "left" else row.right
            if line is None or line.bbox is None:
                continue
            rects[side].setdefault(str(line.page), []).append(
                {
                    "x0": line.bbox[0],
                    "top": line.bbox[1],
                    "x1": line.bbox[2],
                    "bottom": line.bbox[3],
                    "kind": row.kind,
                    "text": line.text,
                }
            )
    return rects


def _render_page(path: Path, index: int, dpi: int) -> bytes:
    cache_key = (str(path), index, dpi)
    cached = _PAGE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        if index < 0 or index >= len(document):
            raise IndexError(f"sayfa {index} yok")
        page = document[index]
        bitmap = page.render(scale=dpi / 72)
        try:
            image = bitmap.to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            data = buffer.getvalue()
        finally:
            bitmap.close()
    finally:
        document.close()

    if len(_PAGE_CACHE) > 256:
        _PAGE_CACHE.clear()
    _PAGE_CACHE[cache_key] = data
    return data


def _remember(comparison: Comparison) -> None:
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


def _summary(comparison: Comparison) -> dict[str, Any]:
    return comparison.payload


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
