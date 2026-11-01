from __future__ import annotations

from pathlib import Path

import pytest

from diffanydoc.desktop import DesktopApi, free_port, run_desktop, wait_until_ready


def test_free_port_is_usable() -> None:
    port = free_port()
    assert 1024 < port < 65536


def test_desktop_api_resolves_startup_paths(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_bytes(b"%PDF-1.4\n")
    second.write_bytes(b"%PDF-1.4\n")

    api = DesktopApi([first, "~"])
    files = api.startup_files()
    assert files[0] == str(first.resolve())
    assert Path(files[1]) == Path("~").expanduser().resolve()


def test_desktop_api_without_window_is_safe() -> None:
    api = DesktopApi()
    assert api.startup_files() == []
    assert api.startup_selection() == {"left": None, "right": None}
    assert api.pick_file() is None
    assert api.app_info()["desktop"] is True


def test_desktop_api_keeps_the_requested_slot(tmp_path: Path) -> None:
    file = tmp_path / "only-right.pdf"
    file.write_bytes(b"%PDF-1.4\n")

    api = DesktopApi([file], startup_slots=["right"])
    assert api.startup_selection() == {"left": None, "right": str(file.resolve())}
    assert api.startup_files() == [str(file.resolve())]


def test_selection_is_queued_until_the_window_has_loaded(tmp_path: Path) -> None:
    calls: list[str] = []

    class Window:
        def evaluate_js(self, script: str) -> None:
            calls.append(script)

    api = DesktopApi()
    api.attach(Window())  # type: ignore[arg-type]
    api.deliver_selection("left", str(tmp_path / "a.pdf"))
    assert calls == []

    api.on_loaded()
    assert len(calls) == 1
    assert "diffanydocReceive" in calls[0]
    assert '"slot": "left"' in calls[0]


def test_selection_after_load_is_pushed_immediately(tmp_path: Path) -> None:
    calls: list[str] = []

    class Window:
        def evaluate_js(self, script: str) -> None:
            calls.append(script)

    api = DesktopApi()
    api.attach(Window())  # type: ignore[arg-type]
    api.on_loaded()
    api.deliver_selection("right", str(tmp_path / "b.pdf"))
    assert len(calls) == 1
    assert '"slot": "right"' in calls[0]


def test_pick_file_uses_supported_dialog_arguments() -> None:
    pytest.importorskip("webview")
    calls: dict[str, object] = {}

    class Window:
        def create_file_dialog(self, *args: object, **kwargs: object) -> list[str]:
            calls["args"] = args
            calls["kwargs"] = kwargs
            return ["/tmp/a.pdf"]

    api = DesktopApi()
    api.attach(Window())  # type: ignore[arg-type]
    assert api.pick_file("en") == "/tmp/a.pdf"

    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    # pywebview's GTK backend does not accept a ``title`` argument.
    assert "title" not in kwargs
    labels = kwargs["file_types"]
    assert isinstance(labels, tuple)
    assert labels[0].startswith("Documents")
    assert labels[1].startswith("All files")


def test_open_external_rejects_unknown_schemes() -> None:
    assert DesktopApi().open_external("javascript:alert(1)") is False


def test_wait_until_ready_times_out_quickly() -> None:
    import time

    started = time.monotonic()
    assert wait_until_ready("http://127.0.0.1:1", timeout=0.3) is False
    assert time.monotonic() - started < 3


def test_run_desktop_without_display_reports_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("webview")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert run_desktop([]) == 2
    assert "graphical session" in capsys.readouterr().out
