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


def _windows_compare_command() -> str:
    argv = [*launcher_argv(), "desktop"]
    return f'{subprocess.list2cmdline(argv)} "%1"'


def _posix_command(slot: str) -> str:
    return shlex.join([*launcher_argv(), "select", slot])


def _posix_compare_command() -> str:
    return shlex.join([*launcher_argv(), "desktop"])


def windows_entries(language: str) -> list[dict[str, str]]:
    """Registry keys, labels and commands for compare and slots."""
    lang = resolve_language(language)
    return [
        {
            "key": rf"{WINDOWS_SHELL}\DiffAnyDoc.Compare",
            "label": t("integrate.compare", lang),
            "command": _windows_compare_command(),
        },
        {
            "key": rf"{WINDOWS_SHELL}\DiffAnyDoc.Left",
            "label": t("integrate.left", lang),
            "command": _windows_command("left"),
        },
        {
            "key": rf"{WINDOWS_SHELL}\DiffAnyDoc.Right",
            "label": t("integrate.right", lang),
            "command": _windows_command("right"),
        },
    ]


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def nautilus_dir() -> Path:
    return data_home() / "nautilus" / "scripts"


def dolphin_dir() -> Path:
    return data_home() / "kio" / "servicemenus"


def nemo_dir() -> Path:
    return data_home() / "nemo" / "actions"


def nautilus_script(slot: str, language: str) -> str:
    if slot == "compare":
        return f"""#!/bin/sh
# Installed by DiffAnyDoc. Removed by `diffanydoc integrate uninstall`.
first=$(printf '%s\\n' "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" | head -n 1)
second=$(printf '%s\\n' "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" | head -n 2 | tail -n 1)
[ -n "$first" ] || first="$1"
[ -n "$second" ] || second="$2"
if [ -n "$first" ] && [ -n "$second" ] && [ "$first" != "$second" ]; then
    exec {_posix_compare_command()} "$first" "$second"
elif [ -n "$first" ]; then
    exec {_posix_compare_command()} "$first"
fi
"""
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
Actions=compare;selectLeft;selectRight;
X-KDE-ServiceTypes=KonqPopupMenu/Plugin
X-KDE-Priority=TopLevel

[Desktop Action compare]
Name={t("integrate.compare", lang)}
Icon=diffanydoc
Exec={_posix_compare_command()} %U

[Desktop Action selectLeft]
Name={t("integrate.left", lang)}
Icon=diffanydoc
Exec={_posix_command("left")} %f

[Desktop Action selectRight]
Name={t("integrate.right", lang)}
Icon=diffanydoc
Exec={_posix_command("right")} %f
"""


def nemo_action(slot: str, language: str) -> str:
    """Nemo (Cinnamon) action: an Exec line plus the selected file."""
    lang = resolve_language(language)
    if slot == "compare":
        return f"""[Nemo Action]
Name={t("integrate.compare", lang)}
Exec={_posix_compare_command()} %F
Icon-Name=diffanydoc
Selection=notnone
Extensions=nodirs;
Quote=double
"""
    return f"""[Nemo Action]
Name={t(f"integrate.{slot}", lang)}
Exec={_posix_command(slot)} %F
Icon-Name=diffanydoc
Selection=s
Extensions=nodirs;
Quote=double
"""


def _nautilus_path(slot: str, language: str) -> Path:
    key = "integrate.compare" if slot == "compare" else f"integrate.{slot}"
    return nautilus_dir() / t(key, resolve_language(language))


def _nemo_path(slot: str) -> Path:
    return nemo_dir() / f"diffanydoc-{slot}.nemo_action"


def is_installed() -> bool:
    """Return whether context menu entries currently exist."""
    if sys.platform == "win32":
        try:
            import winreg

            key = rf"{WINDOWS_SHELL}\DiffAnyDoc.Compare"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
                return True
        except Exception:
            return False
    if sys.platform.startswith("linux"):
        return _nemo_path("compare").is_file() or (dolphin_dir() / _DOLPHIN_FILE).is_file()
    return False


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
    for slot in ("compare", "left", "right"):
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
    for slot in ("compare", "left", "right"):
        path = _nautilus_path(slot, lang)
        path.write_text(nautilus_script(slot, lang), encoding="utf-8")
        path.chmod(0o755)
        installed.append(str(path))

    nemo_dir().mkdir(parents=True, exist_ok=True)
    for slot in ("compare", "left", "right"):
        path = _nemo_path(slot)
        path.write_text(nemo_action(slot, lang), encoding="utf-8")
        installed.append(str(path))

    dolphin_dir().mkdir(parents=True, exist_ok=True)
    service = dolphin_dir() / _DOLPHIN_FILE
    service.write_text(dolphin_service(lang), encoding="utf-8")
    installed.append(str(service))
    return installed


def _uninstall_linux() -> list[str]:
    removed: list[str] = []
    candidates: set[Path] = {
        dolphin_dir() / _DOLPHIN_FILE,
        _nemo_path("compare"),
        _nemo_path("left"),
        _nemo_path("right"),
    }
    for language in available_languages():
        for slot in ("compare", "left", "right"):
            candidates.add(_nautilus_path(slot, language))
    for path in sorted(candidates):
        try:
            path.unlink()
            removed.append(str(path))
        except FileNotFoundError:
            pass
    return removed
