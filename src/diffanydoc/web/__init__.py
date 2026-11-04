"""Web frontend (FastAPI API + static SPA).

Kept light: importing this package must not load FastAPI, so the desktop
window can open before the server is ready.
"""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
