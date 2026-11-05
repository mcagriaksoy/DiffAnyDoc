from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from diffanydoc import integrate


def test_nautilus_scripts_are_installed_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(sys, "platform", "linux")

    installed = integrate.install("en")
    assert len(installed) == 7

    compare = integrate.nautilus_dir() / "Compare with DiffAnyDoc"
    left = integrate.nautilus_dir() / "Select as left file (DiffAnyDoc)"
    right = integrate.nautilus_dir() / "Select as right file (DiffAnyDoc)"
    service = integrate.dolphin_dir() / "diffanydoc-select.desktop"
    nemo_compare = integrate.nemo_dir() / "diffanydoc-compare.nemo_action"
    nemo_left = integrate.nemo_dir() / "diffanydoc-left.nemo_action"
    nemo_right = integrate.nemo_dir() / "diffanydoc-right.nemo_action"
    assert compare.is_file() and left.is_file() and right.is_file() and service.is_file()
    assert nemo_compare.is_file() and nemo_left.is_file() and nemo_right.is_file()
    assert integrate.is_installed() is True
    if os.name == "posix":  # NTFS has no exec bit
        assert left.stat().st_mode & 0o111

    script = left.read_text(encoding="utf-8")
    assert "select left" in script
    assert "NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" in script

    compare_script = compare.read_text(encoding="utf-8")
    assert "desktop" in compare_script

    content = service.read_text(encoding="utf-8")
    assert "Actions=compare;selectLeft;selectRight;" in content
    assert "select right %f" in content

    action = nemo_left.read_text(encoding="utf-8")
    assert "Name=Select as left file (DiffAnyDoc)" in action
    assert "select left %F" in action
    assert "Selection=s" in action and "Quote=double" in action

    removed = integrate.uninstall("en")
    assert len(removed) == 7
    assert not compare.exists() and not left.exists() and not right.exists() and not service.exists()
    assert not nemo_compare.exists() and not nemo_left.exists() and not nemo_right.exists()
    assert integrate.is_installed() is False


def test_uninstall_removes_turkish_script_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(sys, "platform", "linux")

    integrate.install("tr")
    turkish = integrate.nautilus_dir() / "Sol dosya olarak seç (DiffAnyDoc)"
    assert turkish.is_file()

    integrate.uninstall("en")
    assert not turkish.exists()


def test_windows_entries_are_localised_and_quoted() -> None:
    entries = integrate.windows_entries("tr")
    assert [entry["key"] for entry in entries] == [
        r"Software\Classes\*\shell\DiffAnyDoc.Compare",
        r"Software\Classes\*\shell\DiffAnyDoc.Left",
        r"Software\Classes\*\shell\DiffAnyDoc.Right",
    ]
    assert entries[0]["label"] == "DiffAnyDoc ile karşılaştır"
    assert entries[0]["command"].endswith('desktop "%1"')
    assert entries[1]["label"] == "Sol dosya olarak seç (DiffAnyDoc)"
    assert entries[1]["command"].endswith('select left "%1"')
    assert entries[2]["command"].endswith('select right "%1"')


def test_unsupported_platform_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(NotImplementedError):
        integrate.install("en")
