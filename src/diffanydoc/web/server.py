"""Local HTTP API and web UI (FastAPI + static SPA).

The UI talks only to this API, so a React/Electron shell can replace the
frontend later without touching the engine.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..core.adapters import AdapterError, supported_extensions
from ..core.diff import DiffOptions, compare, file_sha256, preload_document
from ..core.model import DiffResult
from ..core.ocr import OcrError, available as ocr_available, installed_languages
from ..core.render import is_renderable_path, render_page_png
from ..core.report.html import render_html
from ..core.report.json import result_to_dict
from ..core.visual import render_xray_page_png
from ..i18n import available_languages, resolve_language, strings
from ..system import accent_color
from . import STATIC_DIR

# FastAPI is an optional extra (``pip install 'diffanydoc[web]'``). Importing
# this module without it raises ImportError, which the CLI turns into a hint.
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

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

    @app.get("/api/updates")
    def updates() -> dict[str, Any]:
        from ..updates import check_for_updates

        return check_for_updates().as_dict()

    @app.get("/api/ocr/status")
    def ocr_status() -> dict[str, Any]:
        return {
            "available": ocr_available(),
            "languages": installed_languages(),
        }

    @app.post("/api/checksum")
    async def checksum_paths(body: dict[str, Any]) -> JSONResponse:
        left_path = Path(str(body.get("left", ""))).expanduser()
        right_path = Path(str(body.get("right", ""))).expanduser()
        if not left_path.is_file() or not right_path.is_file():
            raise HTTPException(status_code=400, detail="both files must exist")
        left_hash = file_sha256(left_path)
        right_hash = file_sha256(right_path)
        return JSONResponse(
            {
                "left_sha256": left_hash,
                "right_sha256": right_hash,
                "byte_identical": left_hash == right_hash,
            }
        )

    @app.post("/api/preload-path")
    async def preload_path_endpoint(body: dict[str, Any]) -> JSONResponse:
        path = Path(str(body.get("path", ""))).expanduser()
        if not path.is_file():
            raise HTTPException(status_code=400, detail="file must exist")
        other_sha = str(body.get("other_sha256") or "")
        digest = file_sha256(path)
        if other_sha and digest == other_sha:
            return JSONResponse(
                {
                    "sha256": digest,
                    "byte_identical": True,
                    "skipped_parse": True,
                }
            )
        ocr = bool(body.get("ocr", True))
        ocr_lang = str(body.get("ocr_language") or "tur+eng")
        digest, doc, _ = preload_document(path, ocr=ocr, ocr_language=ocr_lang)
        return JSONResponse(
            {
                "sha256": digest,
                "kind": doc.kind,
                "pages": len(doc.pages),
                "byte_identical": False,
                "skipped_parse": False,
            }
        )

    @app.post("/api/preload")
    async def preload_upload_endpoint(
        file: UploadFile = File(...),
        other_sha256: str = Form(""),
        ocr: bool = Form(True),
        ocr_language: str = Form("tur+eng"),
    ) -> JSONResponse:
        directory = Path(tempfile.mkdtemp(prefix="diffanydoc-pre-"))
        try:
            stored = _store_upload(file, directory, "preload")
            digest = file_sha256(stored)
            if other_sha256 and digest == other_sha256:
                return JSONResponse(
                    {
                        "sha256": digest,
                        "byte_identical": True,
                        "skipped_parse": True,
                    }
                )
            digest, doc, _ = preload_document(stored, ocr=ocr, ocr_language=ocr_language)
            return JSONResponse(
                {
                    "sha256": digest,
                    "kind": doc.kind,
                    "pages": len(doc.pages),
                    "byte_identical": False,
                    "skipped_parse": False,
                }
            )
        finally:
            shutil.rmtree(directory, ignore_errors=True)

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
        left: UploadFile | None = File(None),
        right: UploadFile | None = File(None),
        left_path: str | None = Form(None),
        right_path: str | None = Form(None),
        context: int = Form(3),
        case_sensitive: bool = Form(True),
        collapse_whitespace: bool = Form(True),
        compare_formatting: bool = Form(False),
        fold_equal: bool = Form(False),
        visual: bool = Form(True),
        ocr: bool = Form(True),
        ocr_language: str = Form("tur+eng"),
    ) -> JSONResponse:
        directory = Path(tempfile.mkdtemp(prefix="diffanydoc-"))
        try:
            if left_path and Path(left_path).is_file():
                resolved_left = Path(left_path).resolve()
            elif left is not None:
                resolved_left = _store_upload(left, directory, "left")
            else:
                raise HTTPException(status_code=400, detail="left file or left_path required")

            if right_path and Path(right_path).is_file():
                resolved_right = Path(right_path).resolve()
            elif right is not None:
                resolved_right = _store_upload(right, directory, "right")
            else:
                raise HTTPException(status_code=400, detail="right file or right_path required")

            comparison = _run_compare(
                resolved_left,
                resolved_right,
                directory,
                context,
                case_sensitive,
                fold_equal,
                collapse_whitespace,
                visual,
                ocr,
                ocr_language,
                compare_formatting,
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
            bool(body.get("visual", True)),
            bool(body.get("ocr", True)),
            str(body.get("ocr_language") or "tur+eng"),
            bool(body.get("compare_formatting", False)),
        )
        return JSONResponse(_summary(comparison))

    @app.get("/api/compare/{comparison_id}")
    def get_comparison(comparison_id: str) -> JSONResponse:
        return JSONResponse(_get(comparison_id).payload)

    @app.get("/api/compare/{comparison_id}/report", response_class=HTMLResponse)
    def get_report(comparison_id: str, lang: str | None = None) -> HTMLResponse:
        return HTMLResponse(render_html(_get(comparison_id).result, language=lang))

    @app.get("/api/compare/{comparison_id}/export/{side}")
    def export_merged(comparison_id: str, side: str) -> Response:
        comparison = _get(comparison_id)
        if side not in ("left", "right"):
            raise HTTPException(status_code=404, detail="invalid side")
        rows = comparison.payload.get("rows") or []
        lines: list[str] = []
        for row in rows:
            cell = row.get(side)
            if cell and cell.get("text") is not None:
                lines.append(str(cell["text"]))
        content = "\n".join(lines) + ("\n" if lines else "")
        source_name = (
            comparison.payload.get(side, {}).get("name")
            or f"merged-{side}.txt"
        )
        stem = Path(source_name).stem or f"merged-{side}"
        suffix = Path(source_name).suffix.lower()
        ext = suffix if suffix in (".txt", ".md", ".csv", ".tsv", ".json", ".py", ".js", ".html", ".css", ".xml", ".yaml", ".yml") else ".txt"
        filename = f"{stem}-merged{ext}"
        return Response(
            content=content.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.get("/api/compare/{comparison_id}/page/{side}/{index}.png")
    def get_page(comparison_id: str, side: str, index: int, dpi: int = 110) -> Response:
        comparison = _get(comparison_id)
        if side not in ("left", "right"):
            raise HTTPException(status_code=404, detail="invalid side")
        path = comparison.left if side == "left" else comparison.right
        if not is_renderable_path(path):
            raise HTTPException(status_code=404, detail="this file cannot be rendered as pages")
        try:
            data = render_page_png(path, index, max(60, min(dpi, 300)))
        except Exception as exc:  # pragma: no cover - renderer specific
            raise HTTPException(status_code=500, detail=f"render failed: {exc}") from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/compare/{comparison_id}/xray/{left_index}/{right_index}.png")
    def get_xray_page(
        comparison_id: str, left_index: int, right_index: int, dpi: int = 110
    ) -> Response:
        comparison = _get(comparison_id)
        if not (is_renderable_path(comparison.left) and is_renderable_path(comparison.right)):
            raise HTTPException(
                status_code=404, detail="both files must be renderable for X-Ray view"
            )
        try:
            data = render_xray_page_png(
                comparison.left,
                left_index,
                comparison.right,
                right_index,
                dpi=max(60, min(dpi, 300)),
            )
        except Exception as exc:  # pragma: no cover - renderer specific
            raise HTTPException(status_code=500, detail=f"xray render failed: {exc}") from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.exception_handler(OcrError)
    async def _ocr_error(_request: Any, exc: OcrError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

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
    visual: bool = True,
    ocr: bool = False,
    ocr_language: str = "eng",
    compare_formatting: bool = False,
) -> Comparison:
    options = DiffOptions(
        context=context,
        case_sensitive=case_sensitive,
        fold_equal=fold_equal,
        collapse_whitespace=collapse_whitespace,
        compare_formatting=compare_formatting,
        visual=visual,
        ocr=ocr,
        ocr_language=ocr_language,
    )
    result = compare(left_path, right_path, options)

    payload = result_to_dict(result)
    payload["id"] = uuid.uuid4().hex if directory else None
    payload["pages"] = {
        "left": [{"width": w, "height": h} for w, h in result.left_pages],
        "right": [{"width": w, "height": h} for w, h in result.right_pages],
    }
    payload["renderable"] = {
        "left": result.left_kind in ("pdf", "image"),
        "right": result.right_kind in ("pdf", "image"),
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
