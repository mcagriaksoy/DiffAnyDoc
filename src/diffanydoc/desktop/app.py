"""Native desktop shell.

The UI is a normal web app served by a local uvicorn instance; pywebview wraps
it in an OS window. Nothing else changes: same engine, same API, same HTML.

Backend note: pywebview uses GTK/WebKit2GTK when available and Qt otherwise.
Neither is bundled, so packaging stays small and no GPL-licensed UI toolkit is
linked in.
"""

from __future__ import annotations

import html
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import url2pathname, urlopen

from .. import __version__
from ..i18n import resolve_language, t
from ..session import SessionServer
from ..web import STATIC_DIR

HOST = "127.0.0.1"
_WINDOW_MIN = (900, 620)


# --------------------------------------------------------------------------- #
# Local server
# --------------------------------------------------------------------------- #


def free_port() -> int:
    """Ask the OS for an unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


class ServerThread(threading.Thread):
    """Uvicorn in a daemon thread, stoppable from the window's closing hook."""

    def __init__(self, port: int, host: str = HOST) -> None:
        super().__init__(daemon=True, name="diffanydoc-http")
        self.host = host
        self.port = port
        self._server: Any = None

    def run(self) -> None:  # pragma: no cover - needs a socket
        # Heavy imports here, off the GUI thread.
        import uvicorn

        from ..web.server import create_app

        config = uvicorn.Config(
            create_app(),
            host=self.host,
            port=self.port,
            log_level="warning",
            # The app has no websocket endpoints; "auto" would pick up a stale
            # system websockets package and fail at import time.
            ws="none",
        )
        self._server = uvicorn.Server(config)
        self._server.run()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def wait_until_ready(url: str, timeout: float = 20.0) -> bool:
    """Poll the health endpoint until the API answers."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{url}/api/health", timeout=1.0) as response:
                if response.status == 200:
                    return True
        except (URLError, OSError):
            time.sleep(0.08)
    return False


# --------------------------------------------------------------------------- #
# JavaScript bridge
# --------------------------------------------------------------------------- #


class DesktopApi:
    """Methods exposed to JS as ``window.pywebview.api.*``."""

    def __init__(
        self,
        startup_paths: Sequence[str | Path] = (),
        startup_slots: Sequence[str | None] | None = None,
    ) -> None:
        self._selection: dict[str, str | None] = {"left": None, "right": None}
        slots = list(startup_slots or ())
        for index, path in enumerate(startup_paths):
            if index < len(slots) and slots[index] in self._selection:
                slot = str(slots[index])
            else:
                slot = "left" if index == 0 else "right"
            self._selection[slot] = _resolve(path)
        self._window: Any = None
        self._loaded = False
        self._pending: list[dict[str, str]] = []

    def attach(self, window: Any) -> None:
        self._window = window

    # -- called by the frontend ------------------------------------------- #

    def app_info(self) -> dict[str, Any]:
        return {"version": __version__, "desktop": True}

    def startup_files(self) -> list[str]:
        """Files passed on the command line, e.g. ``diffanydoc desktop a.pdf b.pdf``."""
        return [path for path in self._selection.values() if path]

    def startup_selection(self) -> dict[str, str | None]:
        """Slot-aware startup state, used by the left/right context menu entries."""
        return dict(self._selection)

    def deliver_selection(self, slot: str, path: str) -> None:
        """Called from the session thread when another process sends a file."""
        if slot not in self._selection:
            return
        resolved = _resolve(path)
        self._selection[slot] = resolved
        payload = {"slot": slot, "path": resolved}
        if not self._loaded or self._window is None:
            self._pending.append(payload)
            return
        self._push(payload)

    def on_loaded(self, *_args: Any) -> None:
        """Flush selections that arrived while the webview was still loading."""
        self._loaded = True
        pending, self._pending = self._pending, []
        for payload in pending:
            self._push(payload)

    def _push(self, payload: dict[str, str]) -> None:
        if self._window is None:
            return
        script = (
            "window.diffanydocReceive && "
            f"window.diffanydocReceive({json.dumps(payload)});"
        )
        try:
            self._window.evaluate_js(script)
        except Exception:
            # The window may be closing; a lost hand-off is not worth a crash.
            pass

    def pick_file(self, language: str = "en") -> str | None:
        if self._window is None:
            return None
        import webview

        lang = resolve_language(language)
        dialog_type = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
        if dialog_type is None:  # older pywebview
            dialog_type = webview.OPEN_DIALOG
        selected = self._window.create_file_dialog(
            dialog_type,
            allow_multiple=False,
            file_types=(
                f"{t('dialog.documents', lang)} (*.pdf;*.docx;*.doc;*.odt;*.rtf;*.xlsx;*.xlsm;*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp;*.webp;*.txt;*.md;*.csv;*.json)",
                f"{t('dialog.allFiles', lang)} (*.*)",
            ),
        )
        if not selected:
            return None
        return str(selected[0])

    def open_external(self, url: str) -> bool:
        """Open a link in the system browser instead of navigating the webview."""
        if not str(url).startswith(("http://", "https://", "file://")):
            return False
        return webbrowser.open(url)

    def resolve_dropped_uris(self, raw: str) -> list[str]:
        """Resolve a ``text/uri-list`` or newline-separated path list dropped onto the window."""
        paths: list[str] = []
        for line in str(raw or "").splitlines():
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            if item.startswith("file://"):
                parsed = urlparse(item)
                # Handles %20 and Windows drive letters (/C:/x).
                candidate = Path(url2pathname(parsed.path))
            else:
                candidate = Path(item).expanduser()
            try:
                if candidate.is_file():
                    paths.append(str(candidate.resolve()))
            except OSError:
                continue
        return paths


def _resolve(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def has_display() -> bool:
    # Only X11/Wayland systems need DISPLAY; Windows and macOS always have one.
    if not sys.platform.startswith(("linux", "freebsd", "openbsd", "netbsd")):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def splash_html(language: str | None = None) -> str:
    """Tiny page shown while the local server starts."""
    text = html.escape(t("app.starting", resolve_language(language)))
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        ":root{color-scheme:light dark}"
        "body{margin:0;height:100vh;display:grid;place-items:center;"
        "font:15px system-ui,sans-serif;background:#fafafb;color:#6b7280}"
        "@media (prefers-color-scheme:dark){body{background:#1d1d20;color:#b0b0b6}}"
        f"</style></head><body>{text}</body></html>"
    )


def window_icon() -> str | None:
    name = "icon.ico" if os.name == "nt" else "icon.png"
    path = STATIC_DIR / name
    return str(path) if path.is_file() else None


def run_desktop(
    paths: Iterable[str | Path] = (),
    width: int = 1280,
    height: int = 860,
    debug: bool = False,
    language: str | None = None,
    slots: Sequence[str | None] | None = None,
) -> int:
    try:
        import webview
    except ImportError:
        print(
            "the desktop window needs an extra dependency:\n"
            "  pip install 'diffanydoc[desktop]'\n"
            "On Linux, GTK/WebKit2GTK or Qt must also be installed.",
        )
        return 2

    if not has_display():
        print(
            "no graphical session found (DISPLAY/WAYLAND_DISPLAY is not set).\n"
            "Use the browser UI instead:  diffanydoc serve",
        )
        return 2

    # Window and server start together; the splash shows until the API answers.
    port = free_port()
    server = ServerThread(port)
    server.start()

    api = DesktopApi(paths, startup_slots=slots)
    url = f"{server.url}/?lang={language}" if language else server.url
    window = webview.create_window(
        f"DiffAnyDoc {__version__}",
        html=splash_html(language),
        width=width,
        height=height,
        min_size=_WINDOW_MIN,
        js_api=api,
        text_select=True,
    )
    api.attach(window)
    window.events.loaded += api.on_loaded
    _attach_native_drop(window, api)

    failed = threading.Event()

    def load_app() -> None:
        if wait_until_ready(server.url):
            window.load_url(url)
            return
        failed.set()
        message = t("app.serverFailed", resolve_language(language))
        print(message)
        window.load_html(f"<p style='font-family:system-ui'>{html.escape(message)}</p>")

    session = SessionServer(api.deliver_selection)
    session.start()
    try:
        webview.start(load_app, debug=debug, icon=window_icon())
    finally:
        session.stop()
        server.stop()
    return 2 if failed.is_set() else 0


def _attach_native_drop(window: Any, api: DesktopApi) -> None:
    """Attach pywebview native DOM drop listener when supported by the backend."""
    try:
        from webview.dom import DOMEventHandler
    except ImportError:
        return

    def on_drop(event: Any) -> None:
        if not isinstance(event, dict):
            return
        data_transfer = event.get("dataTransfer") or {}
        files = data_transfer.get("files") or []
        paths: list[str] = []
        for item in files:
            if isinstance(item, dict):
                full_path = item.get("pywebviewFullPath") or item.get("path")
                if full_path and Path(str(full_path)).is_file():
                    paths.append(str(Path(str(full_path)).resolve()))
        if len(paths) >= 2:
            api.deliver_selection("left", paths[0])
            api.deliver_selection("right", paths[1])
        elif len(paths) == 1:
            slot = "left" if not api._selection.get("left") else "right"
            api.deliver_selection(slot, paths[0])

    def bind_dom() -> None:
        try:
            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            pass

    window.events.loaded += bind_dom
