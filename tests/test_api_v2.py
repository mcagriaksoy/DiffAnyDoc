"""HTTP API additions: visual diff, overlays, images, capabilities, updates."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from diffanydoc import updates
from diffanydoc.core import ocr

from .officegen import table, write_docx
from .pdfgen import write_pdf

pytest.importorskip("httpx")


def _client():
    from fastapi.testclient import TestClient

    from diffanydoc.web.server import create_app

    return TestClient(create_app())


def _compare(client, left: Path, right: Path, **extra):
    response = client.post(
        "/api/compare-paths", json={"left": str(left), "right": str(right), **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_pdf_payload_has_word_rects_and_lazy_visual(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "l.pdf", [["Total: 1000 EUR"], ["Same"]])
    right = write_pdf(tmp_path / "r.pdf", [["Total: 1250 EUR"], ["Same"]])
    client = _client()
    payload = _compare(client, left, right)
    assert payload["visual"] is None
    words = [r for r in payload["rects"]["right"]["0"] if r["level"] == "word"]
    assert words and words[0]["text"] == "1250"

    visual = client.get(f"/api/compare/{payload['id']}/visual").json()
    assert len(visual["pages"]) == 2
    assert visual["pages"][0]["regions"] and visual["pages"][1]["identical"]

    overlay = client.get(f"/api/compare/{payload['id']}/overlay/0.png")
    assert overlay.status_code == 200 and overlay.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(overlay.content)).size[0] > 100

    page = client.get(f"/api/compare/{payload['id']}/page/left/0.png")
    assert page.status_code == 200
    assert client.get(f"/api/compare/{payload['id']}/page/left/9.png").status_code == 404
    assert client.get(f"/api/compare/{payload['id']}/overlay/7.png").status_code == 404


def test_image_comparison_runs_visual_and_renders(tmp_path: Path) -> None:
    ocr.set_engine(None)
    try:
        for name, stamp in (("a.png", False), ("b.png", True)):
            image = Image.new("RGB", (400, 300), "white")
            if stamp:
                ImageDraw.Draw(image).rectangle((200, 150, 300, 220), outline="black", width=4)
            image.save(tmp_path / name)
        client = _client()
        payload = _compare(client, tmp_path / "a.png", tmp_path / "b.png")
        assert payload["identical"] is False
        assert payload["renderable"] == {"left": True, "right": True}
        assert payload["visual"][0]["regions"]
        assert payload["left"]["warnings"][0]["code"] == "ocr_unavailable"
        page = client.get(f"/api/compare/{payload['id']}/page/right/0.png?dpi=300")
        assert Image.open(io.BytesIO(page.content)).size == (400, 300)  # native size
    finally:
        ocr.reset_engine()


def test_docx_upload_with_cells(tmp_path: Path) -> None:
    left = write_docx(tmp_path / "l.docx", [table([["Item", "Price"], ["A", "1"]])])
    right = write_docx(tmp_path / "r.docx", [table([["Item", "Price"], ["A", "2"]])])
    client = _client()
    response = client.post(
        "/api/compare",
        files={"left": ("l.docx", left.read_bytes()), "right": ("r.docx", right.read_bytes())},
        data={"compare_formatting": "true", "ocr_mode": "off"},
    )
    assert response.status_code == 200
    payload = response.json()
    changed = [row for row in payload["rows"] if row["kind"] == "replace"]
    assert changed[0]["cells"][1]["left"] == "1" and changed[0]["cells"][1]["right"] == "2"
    assert payload["options"]["compare_formatting"] is True
    assert payload["renderable"] == {"left": False, "right": False}


def test_unreadable_file_is_a_422_not_a_500(tmp_path: Path) -> None:
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a zip at all")
    good = write_docx(tmp_path / "good.docx", ["<w:p/>"])
    response = _client().post("/api/compare-paths", json={"left": str(bad), "right": str(good)})
    assert response.status_code == 422
    assert "bad.docx" in response.json()["detail"]


def test_invalid_ocr_language_is_rejected(tmp_path: Path) -> None:
    left = tmp_path / "a.txt"
    left.write_text("x", encoding="utf-8")
    response = _client().post(
        "/api/compare-paths",
        json={"left": str(left), "right": str(left), "ocr_lang": "eng; rm -rf"},
    )
    assert response.status_code == 400


def test_capabilities_report_ocr() -> None:
    payload = _client().get("/api/capabilities").json()
    assert ".docx" in payload["extensions"] and ".xlsx" in payload["extensions"]
    assert "available" in payload["ocr"]


def test_updates_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        updates, "check", lambda: updates.UpdateInfo(current="0.2.0", status="update", latest="0.3.0")
    )
    payload = _client().get("/api/updates").json()
    assert payload["status"] == "update" and payload["latest"] == "0.3.0"


# --------------------------------------------------------------------------- #
# Update check logic
# --------------------------------------------------------------------------- #


def test_version_ordering() -> None:
    assert updates.is_newer("0.3.0", "0.2.0")
    assert updates.is_newer("v1.0", "0.9.9")
    assert not updates.is_newer("0.2", "0.2.0")
    assert updates.is_newer("1.0.0", "1.0.0rc2")
    assert updates.is_newer("1.0.0rc2", "1.0.0b1")
    assert not updates.is_newer("1.0.0-beta.1", "1.0.0")


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_check_parses_latest_release(monkeypatch: pytest.MonkeyPatch) -> None:
    body = (
        b'{"tag_name": "v0.3.0", "html_url": "https://example.invalid/r", '
        b'"published_at": "2026-01-01T00:00:00Z", "body": "notes", '
        b'"assets": [{"name": "DiffAnyDoc.zip", "browser_download_url": "https://example.invalid/a", "size": 3}]}'
    )
    seen = {}

    def fake_urlopen(request, timeout):
        seen["ua"] = request.get_header("User-agent")
        return _Response(body)

    monkeypatch.setattr(updates, "urlopen", fake_urlopen)
    info = updates.check(current="0.2.0", url="https://example.invalid/latest")
    assert info.status == "update" and info.latest == "0.3.0"
    assert info.assets[0]["name"] == "DiffAnyDoc.zip"
    assert seen["ua"] == "DiffAnyDoc/0.2.0"  # no personal data in the request


def test_check_handles_no_releases_and_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.error import HTTPError, URLError

    def not_found(request, timeout):
        raise HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(updates, "urlopen", not_found)
    assert updates.check(url="https://example.invalid").status == "no_releases"

    def offline(request, timeout):
        raise URLError("no network")

    monkeypatch.setattr(updates, "urlopen", offline)
    info = updates.check(url="https://example.invalid")
    assert info.status == "error" and "no network" in info.message
