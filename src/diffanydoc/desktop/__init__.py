"""Desktop shell (pywebview + local API server)."""

from __future__ import annotations

from .app import (
    DesktopApi,
    ServerThread,
    free_port,
    run_desktop,
    wait_until_ready,
    window_icon,
)

__all__ = [
    "DesktopApi",
    "ServerThread",
    "free_port",
    "run_desktop",
    "wait_until_ready",
    "window_icon",
]
