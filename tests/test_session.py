from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from diffanydoc import session


@pytest.fixture(autouse=True)
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    return runtime


def test_selection_round_trip(tmp_path: Path) -> None:
    received: list[tuple[str, str]] = []
    ready = threading.Event()

    def on_select(slot: str, path: str) -> None:
        received.append((slot, path))
        ready.set()

    server = session.SessionServer(on_select)
    server.start()
    try:
        target = tmp_path / "b.pdf"
        assert session.session_file().is_file()
        assert session.send_selection("right", target) is True
        assert ready.wait(3.0)
        assert received == [("right", str(target))]
    finally:
        server.stop()

    assert not session.session_file().exists()


def test_no_running_session_returns_false() -> None:
    assert session.send_selection("left", "/tmp/a.pdf") is False


def test_stale_session_file_is_discarded(tmp_path: Path) -> None:
    path = session.session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": 999999, "port": 1, "authkey": "00" * 32}),
        encoding="utf-8",
    )
    assert session.send_selection("left", "/tmp/a.pdf") is False
    assert not path.exists()


def test_unknown_slot_is_rejected() -> None:
    with pytest.raises(ValueError):
        session.send_selection("middle", "/tmp/a.pdf")
