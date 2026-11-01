"""Single-instance hand-off for the file-manager integration.

A second process (for example the one launched by a context menu entry) has to
tell the already running window which file was picked.  The protocol is a
loopback TCP connection guarded by a random per-session key; the connection
details live in a small JSON file in the user's runtime directory.

No third-party dependency and no fixed port: the OS picks one and the file is
private to the user (0600).
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from multiprocessing.connection import AuthenticationError, Client, Listener
from pathlib import Path
from typing import Any, Callable

HOST = "127.0.0.1"
_SLOTS = ("left", "right")


def session_file() -> Path:
    """Per-user location of the running instance descriptor."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "DiffAnyDoc" / "session.json"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "diffanydoc" / "session.json"
    return Path.home() / ".cache" / "diffanydoc" / "session.json"


def _read_session() -> dict[str, Any] | None:
    path = session_file()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        port = int(payload["port"])
        key = bytes.fromhex(str(payload["authkey"]))
        pid = int(payload["pid"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 < port < 65536) or not key or pid <= 0:
        return None
    return {"port": port, "authkey": key, "pid": pid}


def _discard_session() -> None:
    try:
        session_file().unlink()
    except OSError:
        pass


def send_selection(slot: str, path: str | Path) -> bool:
    """Deliver a file selection to a live window, if there is one."""
    if slot not in _SLOTS:
        raise ValueError(f"unknown slot: {slot}")
    info = _read_session()
    if info is None:
        return False
    try:
        with Client((HOST, info["port"]), authkey=info["authkey"]) as connection:
            connection.send({"slot": slot, "path": str(path)})
        return True
    except (AuthenticationError, OSError, EOFError):
        # A stale file from a crashed process should not block future hand-offs.
        _discard_session()
        return False


class SessionServer(threading.Thread):
    """Background listener owned by the running desktop window."""

    def __init__(self, on_select: Callable[[str, str], None]) -> None:
        super().__init__(daemon=True, name="diffanydoc-session")
        self._on_select = on_select
        self._authkey = secrets.token_bytes(32)
        self._listener: Listener = Listener((HOST, 0), authkey=self._authkey)
        self.port = int(self._listener.address[1])
        self._stopped = threading.Event()

    # -- lifecycle -------------------------------------------------------- #

    def start(self) -> None:  # type: ignore[override]
        self._publish()
        super().start()

    def _publish(self) -> None:
        path = session_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "port": self.port,
            "authkey": self._authkey.hex(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def stop(self) -> None:
        self._stopped.set()
        try:
            self._listener.close()
        except OSError:
            pass
        info = _read_session()
        if info is None or info["pid"] == os.getpid():
            _discard_session()

    # -- thread ----------------------------------------------------------- #

    def run(self) -> None:  # pragma: no cover - exercised through send_selection
        while not self._stopped.is_set():
            try:
                connection = self._listener.accept()
            except (OSError, EOFError):
                break
            with connection:
                try:
                    payload = connection.recv()
                except (AuthenticationError, OSError, EOFError):
                    continue
                if not isinstance(payload, dict):
                    continue
                slot = payload.get("slot")
                path = payload.get("path")
                if slot in _SLOTS and isinstance(path, str) and path:
                    self._on_select(slot, path)
