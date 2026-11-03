"""Frozen-build entry point and launcher selection."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from diffanydoc import integrate

ROOT = Path(__file__).parent.parent


def _entry():
    spec = importlib.util.spec_from_file_location("entry", ROOT / "packaging" / "entry.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entry_routes_arguments() -> None:
    entry = _entry()
    assert entry._arguments([]) == ["desktop"]
    assert entry._arguments(["a.pdf", "b.pdf"]) == ["desktop", "a.pdf", "b.pdf"]
    assert entry._arguments(["diff", "a", "b"]) == ["diff", "a", "b"]
    assert entry._arguments(["select", "left", "x.pdf"]) == ["select", "left", "x.pdf"]
    assert entry._arguments(["--version"]) == ["--version"]


def test_entry_knows_every_cli_command() -> None:
    from diffanydoc.cli import build_parser

    parser = build_parser()
    subparsers = next(a for a in parser._actions if a.dest == "command")
    assert set(subparsers.choices) == _entry().COMMANDS


def test_frozen_launcher_prefers_the_windowed_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = ".exe" if sys.platform == "win32" else ""
    cli = tmp_path / f"diffanydoc-cli{suffix}"
    cli.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(cli))
    assert integrate.launcher_argv() == [str(cli)]  # no windowed sibling
    windowed = tmp_path / f"DiffAnyDoc{suffix}"
    windowed.write_bytes(b"")
    assert integrate.launcher_argv() == [str(windowed)]
