"""Tests import from the src layout; make the package importable in-place."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
