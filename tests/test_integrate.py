from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from diffanydoc import integrate
from diffanydoc.cli import main


def test_single_entry_linux_installed_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(sys, "platform", "linux")

    installed = integrate.install("en")
    assert len(installed) == 3

    nautilus_script = integrate.nautilus_dir() / "Select as left file to compare"
    service = integrate.dolphin_dir() / "diffanydoc-select.desktop"
    nemo_action = integrate.nemo_dir() / "diffanydoc.nemo_action"

    assert nautilus_script.is_file() and service.is_file() and nemo_action.is_file()
    assert integrate.is_installed() is True
    if os.name == "posix":
        assert nautilus_script.stat().st_mode & 0o111

    script = nautilus_script.read_text(encoding="utf-8")
    assert "context-action" in script

    content = service.read_text(encoding="utf-8")
    assert "Actions=contextAction;" in content
    assert "context-action %U" in content
    assert "Name=Select as left file to compare" in content

    action = nemo_action.read_text(encoding="utf-8")
    assert "Name=Select as left file to compare" in action
    assert "context-action %F" in action
    assert "Selection=notnone" in action and "Quote=double" in action

    removed = integrate.uninstall("en")
    assert len(removed) >= 3
    assert not nautilus_script.exists() and not service.exists() and not nemo_action.exists()
    assert integrate.is_installed() is False


def test_dynamic_selection_label_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(sys, "platform", "linux")

    file_a = tmp_path / "contract_v1.pdf"
    file_a.write_text("Left content", encoding="utf-8")

    file_b = tmp_path / "contract_v2.pdf"
    file_b.write_text("Right content", encoding="utf-8")

    integrate.install("en")
    assert integrate.get_pending_selection() is None
    assert integrate.current_label("en") == "Select as left file to compare"

    # Step 1: Select File A
    integrate.set_pending_selection(file_a, "en")
    assert integrate.get_pending_selection() == file_a
    assert integrate.current_label("en") == "Compare to 'contract_v1.pdf'"

    # Check files updated dynamically
    nemo_content = (integrate.nemo_dir() / "diffanydoc.nemo_action").read_text(encoding="utf-8")
    assert "Name=Compare to 'contract_v1.pdf'" in nemo_content

    nautilus_new_script = integrate.nautilus_dir() / "Compare to 'contract_v1.pdf'"
    assert nautilus_new_script.is_file()
    assert not (integrate.nautilus_dir() / "Select as left file to compare").exists()

    # Step 2: Clear selection
    integrate.clear_pending_selection("en")
    assert integrate.get_pending_selection() is None
    assert integrate.current_label("en") == "Select as left file to compare"

    nemo_reset = (integrate.nemo_dir() / "diffanydoc.nemo_action").read_text(encoding="utf-8")
    assert "Name=Select as left file to compare" in nemo_reset

    assert (integrate.nautilus_dir() / "Select as left file to compare").is_file()
    assert not nautilus_new_script.exists()

    integrate.uninstall("en")


def test_uninstall_removes_turkish_script_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(sys, "platform", "linux")

    integrate.install("tr")
    turkish = integrate.nautilus_dir() / "Karşılaştırmak için sol dosya olarak seç"
    assert turkish.is_file()

    integrate.uninstall("en")
    assert not turkish.exists()


def test_windows_single_entry_localised_and_quoted() -> None:
    entries = integrate.windows_entries("tr")
    assert len(entries) == 1
    assert entries[0]["key"] == r"Software\Classes\*\shell\DiffAnyDoc"
    assert entries[0]["label"] == "Karşılaştırmak için sol dosya olarak seç"
    assert entries[0]["command"].endswith('context-action "%1"')


def test_cli_context_action_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(sys, "platform", "linux")

    f1 = tmp_path / "doc1.txt"
    f1.write_text("Hello", encoding="utf-8")
    f2 = tmp_path / "doc2.txt"
    f2.write_text("World", encoding="utf-8")

    integrate.install("en")

    launched = []
    monkeypatch.setattr("diffanydoc.cli._launch_comparison", lambda left, right, lang: launched.append((left, right)) or 0)
    monkeypatch.setattr("diffanydoc.session.send_selection", lambda slot, path: False)

    # 1. Single click on f1 -> sets pending left
    code1 = main(["context-action", str(f1)])
    assert code1 == 0
    assert integrate.get_pending_selection() == f1
    assert len(launched) == 0

    # 2. Subsequent click on f2 -> launches comparison and clears pending
    code2 = main(["context-action", str(f2)])
    assert code2 == 0
    assert len(launched) == 1
    assert launched[0] == (f1, f2)
    assert integrate.get_pending_selection() is None

    # 3. Two files passed simultaneously -> launches comparison immediately
    launched.clear()
    code3 = main(["context-action", str(f1), str(f2)])
    assert code3 == 0
    assert len(launched) == 1
    assert launched[0] == (f1, f2)

    integrate.uninstall("en")


def test_unsupported_platform_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(NotImplementedError):
        integrate.install("en")
