"""Frozen-build entry point and launcher selection."""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

from diffanydoc import __version__, integrate

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


def _build():
    spec = importlib.util.spec_from_file_location("build_tool", ROOT / "tools" / "build.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_artifact_names_and_targets_per_platform() -> None:
    build = _build()
    names = {
        build.artifact_name("1.2.3", plat, "x86_64", kind)
        for plat in ("windows", "linux")
        for kind in build.targets(plat)
    }
    assert names == {
        "DiffAnyDoc-1.2.3-windows-x86_64-portable.exe",
        "DiffAnyDoc-1.2.3-windows-x86_64-portable.zip",
        "DiffAnyDoc-1.2.3-windows-x86_64-installer.exe",
        "DiffAnyDoc-1.2.3-linux-x86_64.AppImage",
        "DiffAnyDoc-1.2.3-linux-x86_64.tar.gz",
    }
    with pytest.raises(SystemExit):
        build.targets("macos")


def test_missing_build_tool_fails_with_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    build = _build()
    monkeypatch.setattr(shutil, "which", lambda *args, **kwargs: None)
    with pytest.raises(SystemExit, match="Inno Setup"):
        build.find_tool("installer")
    with pytest.raises(SystemExit, match="appimagetool"):
        build.find_tool("appimage")


def test_version_matches_pyproject() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', text, re.M).group(1) == __version__


def test_installer_script_takes_values_from_build() -> None:
    iss = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    for define in ("AppVersion", "SourceDir", "OutputDir", "OutputName", "IconFile"):
        assert "{#%s}" % define in iss
