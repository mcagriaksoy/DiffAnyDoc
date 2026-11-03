"""Tests for update check against GitHub releases."""

from __future__ import annotations

import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from diffanydoc import updates
from diffanydoc.web.server import create_app


def test_version_ordering() -> None:
    assert updates.is_newer("0.3.0", "0.2.0")
    assert updates.is_newer("v1.0", "0.9.9")
    assert not updates.is_newer("0.2", "0.2.0")
    assert updates.is_newer("1.0.0", "1.0.0rc2")
    assert updates.is_newer("1.0.0rc2", "1.0.0b1")
    assert not updates.is_newer("1.0.0-beta.1", "1.0.0")


class _MockResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_check_for_updates_latest() -> None:
    body = json.dumps({"tag_name": "v0.2.0", "html_url": "https://example.com"}).encode("utf-8")
    with patch("diffanydoc.updates.urlopen", return_value=_MockResponse(body)):
        info = updates.check_for_updates(current="0.2.0")
        assert info.status == "latest"
        assert info.latest == "0.2.0"


def test_check_for_updates_available() -> None:
    body = json.dumps({"tag_name": "v0.3.0", "html_url": "https://example.com"}).encode("utf-8")
    with patch("diffanydoc.updates.urlopen", return_value=_MockResponse(body)):
        info = updates.check_for_updates(current="0.2.0")
        assert info.status == "update"
        assert info.latest == "0.3.0"


def test_check_for_updates_404_no_releases() -> None:
    error = HTTPError("url", 404, "Not Found", {}, None)  # type: ignore[arg-type]
    with patch("diffanydoc.updates.urlopen", side_effect=error):
        info = updates.check_for_updates()
        assert info.status == "no_releases"


def test_updates_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        updates, "check_for_updates", lambda: updates.UpdateInfo(current="0.2.0", status="update", latest="0.3.0")
    )
    client = TestClient(create_app())
    payload = client.get("/api/updates").json()
    assert payload["status"] == "update"
    assert payload["latest"] == "0.3.0"
