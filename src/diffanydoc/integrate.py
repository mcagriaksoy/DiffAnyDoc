"""File-manager context menu entries ("select as left/right file").

Windows uses the per-user registry (``HKCU\\Software\\Classes\\*\\shell``), so no
administrator rights are needed.  Linux has no cross-desktop API: Nautilus only
allows scripts and Dolphin/KDE uses service menus, so both are installed.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from .i18n import available_languages, resolve_language, t

WINDOWS_SHELL = r"Software\Classes\*\shell"
_DOLPHIN_FILE = "diffanydoc-select.desktop"


def launcher_argv() -> list[str]:
    """Command that starts this app, whether frozen or running from source."""
    if getattr(sys, "frozen", False):
        # Frozen builds ship a windowed DiffAnyDoc next to the console
        # diffanydoc-cli; the context menu must start the windowed one, or a
        # console window flashes up on every click (Windows).
        executable = Path(sys.executable)
        suffix = ".exe" if sys.platform == "win32" else ""
        windowed = executable.with_name(f"DiffAnyDoc{suffix}")
        return [str(windowed if windowed.is_file() else executable)]
    return [sys.executable, "-m", "diffanydoc"]


def _windows_command(slot: str) -> str:
    argv = [*launcher_argv(), "select", slot]
    return f'{subprocess.list2cmdline(argv)} "%1"'


def _posix_command(slot: str) -> str:
    return shlex.join([*launcher_argv(), "select", slot])


def windows_entries(language: str) -> list[dict[str, str]]:
    """Registry keys, labels and commands for both slots."""
    lang = resolve_language(language)
    entries: list[dict[str, str]] = []
    for slot in ("left", "right"):
        entries.append(
            {
                "key": rf"{WINDOWS_SHELL}\DiffAnyDoc.{slot.capitalize()}",
                "label": t(f"integrate.{slot}", lang),
                "command": _windows_command(slot),
            }
        )
    return entries


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def nautilus_dir() -> Path:
    return data_home() / "nautilus" / "scripts"


def dolphin_dir() -> Path:
    return data_home() / "kio" / "servicemenus"


def nautilus_script(slot: str, language: str) -> str:
    return f"""#!/bin/sh
# Installed by DiffAnyDoc. Removed by `diffanydoc integrate uninstall`.
file=$(printf '%s\\n' "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" | head -n 1)
[ -n "$file" ] || file="$1"
[ -n "$file" ] || exit 0
exec {_posix_command(slot)} "$file"
"""


def dolphin_service(language: str) -> str:
    lang = resolve_language(language)
    return f"""[Desktop Entry]
Type=Service
MimeType=all/allfiles;
Actions=selectLeft;selectRight;
X-KDE-ServiceTypes=KonqPopupMenu/Plugin
X-KDE-Priority=TopLevel

[Desktop Action selectLeft]
Name={t("integrate.left", lang)}
Exec={_posix_command("left")} %f

[Desktop Action selectRight]
Name={t("integrate.right", lang)}
Exec={_posix_command("right")} %f
"""


def _nautilus_path(slot: str, language: str) -> Path:
    return nautilus_dir() / t(f"integrate.{slot}", resolve_language(language))


def install(language: str = "en") -> list[str]:
    if sys.platform == "win32":
        return _install_windows(language)
    if sys.platform.startswith("linux"):
        return _install_linux(language)
    raise NotImplementedError(t("integrate.unsupported", resolve_language(language)))


def uninstall(language: str = "en") -> list[str]:
    if sys.platform == "win32":
        return _uninstall_windows()
    if sys.platform.startswith("linux"):
        return _uninstall_linux()
    raise NotImplementedError(t("integrate.unsupported", resolve_language(language)))


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #


def _install_windows(language: str) -> list[str]:
    import winreg

    installed: list[str] = []
    icon = launcher_argv()[0] if getattr(sys, "frozen", False) else ""
    for entry in windows_entries(language):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, entry["key"]) as key:
            winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, entry["label"])
            if icon:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, f"{icon},0")
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, entry["key"] + r"\command"
        ) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, entry["command"])
        installed.append(entry["key"])
    return installed


def _uninstall_windows() -> list[str]:
    import winreg

    removed: list[str] = []
    for slot in ("left", "right"):
        key = rf"{WINDOWS_SHELL}\DiffAnyDoc.{slot.capitalize()}"
        for name in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)
                removed.append(name)
            except FileNotFoundError:
                pass
    return removed


# --------------------------------------------------------------------------- #
# Linux
# --------------------------------------------------------------------------- #


def _install_linux(language: str) -> list[str]:
    lang = resolve_language(language)
    installed: list[str] = []

    nautilus_dir().mkdir(parents=True, exist_ok=True)
    for slot in ("left", "right"):
        path = _nautilus_path(slot, lang)
        path.write_text(nautilus_script(slot, lang), encoding="utf-8")
        path.chmod(0o755)
        installed.append(str(path))

    dolphin_dir().mkdir(parents=True, exist_ok=True)
    service = dolphin_dir() / _DOLPHIN_FILE
    service.write_text(dolphin_service(lang), encoding="utf-8")
    installed.append(str(service))
    return installed


def _uninstall_linux() -> list[str]:
    removed: list[str] = []
    candidates: set[Path] = {dolphin_dir() / _DOLPHIN_FILE}
    for language in available_languages():
        for slot in ("left", "right"):
            candidates.add(_nautilus_path(slot, language))
    for path in sorted(candidates):
        try:
            path.unlink()
            removed.append(str(path))
        except FileNotFoundError:
            pass
    return removed
