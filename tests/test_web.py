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
