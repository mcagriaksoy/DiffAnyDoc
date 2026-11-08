from __future__ import annotations

import re
from pathlib import Path

import pytest

from diffanydoc import system

from .pdfgen import write_pdf

pytest.importorskip("httpx")


def _client():
    from fastapi.testclient import TestClient

    from diffanydoc.web.server import create_app

    return TestClient(create_app())


def test_accent_falls_back_without_desktop_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system.shutil, "which", lambda _name: None)
    system.accent_color.cache_clear()
    try:
        assert system.accent_color() == system.FALLBACK_ACCENT
    finally:
        system.accent_color.cache_clear()


def test_accent_uses_gnome_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "_gnome_accent", lambda: "#9141ac")
    system.accent_color.cache_clear()
    try:
        assert system.accent_color() == "#9141ac"
    finally:
        system.accent_color.cache_clear()


def test_theme_endpoint_returns_hex_accent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("diffanydoc.web.server.accent_color", lambda: "#3a944a")
    payload = _client().get("/api/system/theme").json()
    assert payload["accent"] == "#3a944a"
    assert payload["platform"]
    assert re.fullmatch(r"#[0-9a-f]{6}", payload["accent"].lower())


def test_compare_respects_whitespace_option() -> None:
    client = _client()
    files = {
        "left": ("a.txt", b"alpha  beta\n"),
        "right": ("b.txt", b"alpha beta\n"),
    }

    collapsed = client.post("/api/compare", files=files, data={"fold_equal": "false"})
    assert collapsed.status_code == 200
    assert collapsed.json()["identical"] is True

    exact = client.post(
        "/api/compare",
        files=files,
        data={"fold_equal": "false", "collapse_whitespace": "false"},
    )
    assert exact.status_code == 200
    assert exact.json()["identical"] is False


def test_path_comparison_is_stored_for_report_and_pages(tmp_path: Path) -> None:
    left = tmp_path / "a.txt"
    right = tmp_path / "b.txt"
    left.write_text("bir\niki\n", encoding="utf-8")
    right.write_text("bir\nüç\n", encoding="utf-8")

    client = _client()
    response = client.post(
        "/api/compare-paths",
        json={"left": str(left), "right": str(right), "fold_equal": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["id"], str) and payload["id"]

    deep_link = client.get(f"/api/compare/{payload['id']}")
    assert deep_link.status_code == 200

    report = client.get(f"/api/compare/{payload['id']}/report?lang=en")
    assert report.status_code == 200
    assert "DiffAnyDoc" in report.text


def test_compare_payload_includes_visual_diff(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "api-l.pdf", [["Invoice", "Total: 1000 EUR"]])
    right = write_pdf(tmp_path / "api-r.pdf", [["Invoice", "Total: 1250 EUR"]])

    client = _client()
    response = client.post(
        "/api/compare-paths",
        json={"left": str(left), "right": str(right)},
    )
    assert response.status_code == 200
    visual = response.json()["visual"]
    assert visual["available"] is True
    assert visual["stats"]["compared"] == 1
    assert visual["stats"]["changed_pages"] == 1
    assert visual["stats"]["regions"] > 0
    assert 0 < visual["stats"]["similarity"] < 1
    page = visual["pages"][0]
    assert page["left"] == 0 and page["right"] == 0
    assert page["left_regions"] and page["right_regions"]


def test_visual_can_be_disabled_per_request(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "off-l.pdf", [["Invoice"]])
    right = write_pdf(tmp_path / "off-r.pdf", [["Invoice"]])

    client = _client()
    response = client.post(
        "/api/compare-paths",
        json={"left": str(left), "right": str(right), "visual": False},
    )
    assert response.status_code == 200
    assert response.json()["visual"] is None


def test_compare_paths_rejects_missing_files(tmp_path: Path) -> None:
    client = _client()
    response = client.post(
        "/api/compare-paths",
        json={"left": str(tmp_path / "yok-a.txt"), "right": str(tmp_path / "yok-b.txt")},
    )
    assert response.status_code == 400


def test_checksum_and_ocr_status_endpoints(tmp_path: Path) -> None:
    left = tmp_path / "a.txt"
    right = tmp_path / "b.txt"
    left.write_text("aynı içerik\n", encoding="utf-8")
    right.write_text("aynı içerik\n", encoding="utf-8")

    client = _client()
    chk = client.post(
        "/api/checksum",
        json={"left": str(left), "right": str(right)},
    )
    assert chk.status_code == 200
    data = chk.json()
    assert data["byte_identical"] is True
    assert data["left_sha256"] == data["right_sha256"]

    ocr = client.get("/api/ocr/status")
    assert ocr.status_code == 200
    assert isinstance(ocr.json()["languages"], list)


def test_export_merged_side_endpoint(tmp_path: Path) -> None:
    left = tmp_path / "sol.txt"
    right = tmp_path / "sag.txt"
    left.write_text("satır 1\nsatır 2 sol\n", encoding="utf-8")
    right.write_text("satır 1\nsatır 2 sağ\n", encoding="utf-8")

    client = _client()
    comp = client.post(
        "/api/compare-paths",
        json={"left": str(left), "right": str(right), "fold_equal": False},
    ).json()

    exp_left = client.get(f"/api/compare/{comp['id']}/export/left")
    assert exp_left.status_code == 200
    assert "satır 2 sol" in exp_left.text

    exp_right = client.get(f"/api/compare/{comp['id']}/export/right")
    assert exp_right.status_code == 200
    assert "satır 2 sağ" in exp_right.text


def test_xray_page_endpoint_returns_composite_png(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "x-l.pdf", [["Invoice", "Total: 1000 EUR"]])
    right = write_pdf(tmp_path / "x-r.pdf", [["Invoice", "Total: 1250 EUR"]])

    client = _client()
    comp = client.post(
        "/api/compare-paths",
        json={"left": str(left), "right": str(right)},
    ).json()

    xray = client.get(f"/api/compare/{comp['id']}/xray/0/0.png?dpi=96")
    assert xray.status_code == 200
    assert xray.headers["content-type"] == "image/png"
    assert xray.content.startswith(b"\x89PNG")


def test_preload_endpoints_warm_cache_and_detect_identical_second_file(tmp_path: Path) -> None:
    first = tmp_path / "p1.txt"
    second = tmp_path / "p2.txt"
    same = tmp_path / "same.txt"
    first.write_text("merhaba dünya\n", encoding="utf-8")
    second.write_text("merhaba evren\n", encoding="utf-8")
    same.write_text("merhaba dünya\n", encoding="utf-8")

    client = _client()
    r1 = client.post(
        "/api/preload-path",
        json={"path": str(first), "ocr": False},
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["skipped_parse"] is False
    assert d1["kind"] == "text"
    assert d1["sha256"]

    # If the 2nd selected file has the same SHA-256, parsing is skipped immediately
    r_same = client.post(
        "/api/preload-path",
        json={"path": str(same), "other_sha256": d1["sha256"], "ocr": False},
    )
    assert r_same.status_code == 200
    assert r_same.json()["byte_identical"] is True
    assert r_same.json()["skipped_parse"] is True

    # Upload preload endpoint also works
    r_up = client.post(
        "/api/preload",
        files={"file": ("p2.txt", second.read_bytes())},
        data={"other_sha256": d1["sha256"], "ocr": "false"},
    )
    assert r_up.status_code == 200
    assert r_up.json()["byte_identical"] is False
    assert r_up.json()["skipped_parse"] is False


def test_app_js_syntax_and_integrity() -> None:
    from diffanydoc.web import STATIC_DIR

    js_file = STATIC_DIR / "app.js"
    assert js_file.is_file()
    content = js_file.read_text(encoding="utf-8")

    assert content.count("{") == content.count("}")
    assert content.count("(") == content.count(")")
    assert content.count("[") == content.count("]")


def test_search_and_filters_markup_and_scripts() -> None:
    from diffanydoc.web import STATIC_DIR

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="search-bar"' in html
    assert 'id="search-input"' in html
    assert 'id="search-toggle"' in html
    assert 'data-filter="all"' in html
    assert 'data-filter="add"' in html
    assert 'data-filter="del"' in html
    assert 'data-filter="mod"' in html

    assert "performSearch" in js
    assert "applyKindFilter" in js
    assert "search-match" in js


def test_stats_detail_dialog_markup_and_scripts() -> None:
    from diffanydoc.web import STATIC_DIR

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="stats-detail-dialog"' in html
    assert 'id="stats-detail-tbody"' in html
    assert 'id="stats-breakdown"' in html
    assert "openStatsDetails" in js





