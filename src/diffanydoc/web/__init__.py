"""Web frontend (FastAPI API + static SPA)."""

from __future__ import annotations

from .server import create_app, run

__all__ = ["create_app", "run"]
