"""Entry point for the frozen (PyInstaller) builds.

``DiffAnyDoc`` with no arguments opens the desktop window; with files it opens
them; with a command (``diff``, ``select``, ...) it behaves like the CLI. The
file-manager integration and "Open with" both rely on this.
"""

from __future__ import annotations

import multiprocessing
import sys

COMMANDS = {
    "diff",
    "info",
    "formats",
    "serve",
    "desktop",
    "select",
    "integrate",
    "context-action",
    "check-update",
}


def _arguments(argv: list[str]) -> list[str]:
    if not argv:
        return ["desktop"]
    first = argv[0]
    if first in COMMANDS or first.startswith("-"):
        return argv
    # "DiffAnyDoc a.pdf b.pdf" (Open with, drag onto the icon).
    return ["desktop", *argv[:2]]


def main() -> int:
    multiprocessing.freeze_support()
    from diffanydoc.cli import main as cli_main

    return cli_main(_arguments(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
