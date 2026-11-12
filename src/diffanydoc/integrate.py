"""File-manager context menu entries ("Select as left file to compare" -> "Compare to <file>").

Provides a single smart right-click context menu item across file managers:
- On first click on File A: remembers File A as the left document and updates the menu label to
  "Compare to <File A>".
- On subsequent click on File B: launches DiffAnyDoc comparing File A and File B, then resets
  the menu label back to "Select as left file to compare".
- If 2 files are selected simultaneously: immediately compares both files.

Windows uses the per-user registry (``HKCU\\Software\\Classes\\*\\shell``), so no
administrator rights are needed. Linux supports Nemo (Cinnamon actions),
Nautilus (GNOME scripts), and Dolphin (KDE service menus).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
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


def _windows_context_command() -> str:
    argv = [*launcher_argv(), "context-action"]
    return f'{subprocess.list2cmdline(argv)} "%1"'


def _posix_context_command() -> str:
    return shlex.join([*launcher_argv(), "context-action"])


# Legacy commands preserved for compatibility if called directly
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


# --------------------------------------------------------------------------- #
# Pending selection state management
# --------------------------------------------------------------------------- #


def state_file() -> Path:
    """Location of the pending left file selection descriptor."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "DiffAnyDoc" / "context_selection.json"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "diffanydoc" / "context_selection.json"
    return Path.home() / ".cache" / "diffanydoc" / "context_selection.json"


def get_pending_selection() -> Path | None:
    """Return the currently selected left file if one is pending and still exists."""
    path = state_file()
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        target = Path(data.get("path", "")).expanduser().resolve()
        if target.exists():
            return target
        # Clean up stale reference if target was moved/deleted
        clear_pending_selection()
        return None
    except Exception:
        return None


def set_pending_selection(path: Path | str, language: str = "en") -> None:
    """Record target as pending left file and update menu labels."""
    target = Path(path).expanduser().resolve()
    s_file = state_file()
    try:
        s_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "path": str(target),
            "name": target.name,
            "timestamp": time.time(),
        }
        s_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    refresh_entries(language)


def clear_pending_selection(language: str = "en") -> None:
    """Clear any pending left file and revert context menu labels to default."""
    try:
        state_file().unlink()
    except OSError:
        pass
    refresh_entries(language)


def current_label(language: str = "en") -> str:
    """Return the context menu label according to current pending selection."""
    lang = resolve_language(language)
    pending = get_pending_selection()
    if pending:
        return t("integrate.compareTo", lang, name=pending.name)
    return t("integrate.selectLeft", lang)


def notify_selection(path: Path, language: str = "en") -> None:
    """Send a lightweight desktop notification confirming file selection."""
    lang = resolve_language(language)
    msg = t("integrate.selectedNotify", lang, name=path.name)
    title = "DiffAnyDoc"
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "-a", title, "-i", "diffanydoc", title, msg],
                timeout=2.0,
                check=False,
            )
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Paths & templates
# --------------------------------------------------------------------------- #


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def nautilus_dir() -> Path:
    return data_home() / "nautilus" / "scripts"


def dolphin_dir() -> Path:
    return data_home() / "kio" / "servicemenus"


def nemo_dir() -> Path:
    return data_home() / "nemo" / "actions"


def _nemo_single_path() -> Path:
    return nemo_dir() / "diffanydoc.nemo_action"


def _nemo_path(slot: str) -> Path:
    return nemo_dir() / f"diffanydoc-{slot}.nemo_action"


def _nautilus_path(slot: str, language: str) -> Path:
    key = "integrate.compare" if slot == "compare" else f"integrate.{slot}"
    return nautilus_dir() / t(key, resolve_language(language))


def nautilus_script(language: str = "en") -> str:
    return f"""#!/bin/sh
# Installed by DiffAnyDoc. Removed by `diffanydoc integrate uninstall`.
exec {_posix_context_command()} "$@"
"""


def dolphin_service(language: str = "en") -> str:
    lang = resolve_language(language)
    label = current_label(lang)
    return f"""[Desktop Entry]
Type=Service
MimeType=all/allfiles;
Actions=contextAction;
X-KDE-ServiceTypes=KonqPopupMenu/Plugin
X-KDE-Priority=TopLevel

[Desktop Action contextAction]
Name={label}
Icon=diffanydoc
Exec={_posix_context_command()} %U
"""


def nemo_action(language: str = "en") -> str:
    """Nemo (Cinnamon) single smart action."""
    lang = resolve_language(language)
    label = current_label(lang)
    return f"""[Nemo Action]
Name={label}
Exec={_posix_context_command()} %F
Icon-Name=diffanydoc
Selection=notnone
Extensions=nodirs;
Quote=double
"""


def windows_entries(language: str = "en") -> list[dict[str, str]]:
    """Registry keys, labels and commands for DiffAnyDoc context menu."""
    lang = resolve_language(language)
    return [
        {
            "key": rf"{WINDOWS_SHELL}\DiffAnyDoc",
            "label": current_label(lang),
            "command": _windows_context_command(),
        }
    ]


# --------------------------------------------------------------------------- #
# Status & Lifecycle
# --------------------------------------------------------------------------- #


def is_installed() -> bool:
    """Return whether context menu entries currently exist."""
    if sys.platform == "win32":
        try:
            import winreg

            key = rf"{WINDOWS_SHELL}\DiffAnyDoc"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
                return True
        except Exception:
            return False
    if sys.platform.startswith("linux"):
        if _nemo_single_path().is_file() or (dolphin_dir() / _DOLPHIN_FILE).is_file():
            return True
        if _nemo_path("compare").is_file():
            return True
        if nautilus_dir().is_dir():
            for p in nautilus_dir().iterdir():
                if p.is_file():
                    try:
                        content = p.read_text(encoding="utf-8")
                        if "Installed by DiffAnyDoc" in content:
                            return True
                    except Exception:
                        pass
        return False
    return False


def refresh_entries(language: str = "en") -> None:
    """Update context menu labels on disk/registry to reflect pending selection."""
    if not is_installed():
        return
    lang = resolve_language(language)
    label = current_label(lang)

    if sys.platform == "win32":
        try:
            import winreg

            key_path = rf"{WINDOWS_SHELL}\DiffAnyDoc"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, label)
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        # Nemo
        nemo_file = _nemo_single_path()
        if nemo_file.is_file() or nemo_dir().is_dir():
            try:
                nemo_file.write_text(nemo_action(lang), encoding="utf-8")
            except OSError:
                pass

        # Dolphin
        service_file = dolphin_dir() / _DOLPHIN_FILE
        if service_file.is_file() or dolphin_dir().is_dir():
            try:
                service_file.write_text(dolphin_service(lang), encoding="utf-8")
            except OSError:
                pass

        # Nautilus
        if nautilus_dir().is_dir():
            target_path = nautilus_dir() / label
            try:
                for p in nautilus_dir().iterdir():
                    if p.is_file():
                        try:
                            if "Installed by DiffAnyDoc" in p.read_text(encoding="utf-8") and p != target_path:
                                p.unlink()
                        except Exception:
                            pass
                target_path.write_text(nautilus_script(lang), encoding="utf-8")
                target_path.chmod(0o755)
            except OSError:
                pass


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

    # Clean up legacy 3-entry slots if present
    for slot in ("Compare", "Left", "Right"):
        old_key = rf"{WINDOWS_SHELL}\DiffAnyDoc.{slot}"
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, old_key + r"\command")
        except OSError:
            pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, old_key)
        except OSError:
            pass
    return installed


def _uninstall_windows() -> list[str]:
    import winreg

    removed: list[str] = []
    # Remove single-entry
    key = rf"{WINDOWS_SHELL}\DiffAnyDoc"
    for name in (key + r"\command", key):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)
            removed.append(name)
        except OSError:
            pass

    # Remove legacy entries
    for slot in ("Compare", "Left", "Right"):
        old_key = rf"{WINDOWS_SHELL}\DiffAnyDoc.{slot}"
        for name in (old_key + r"\command", old_key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)
                removed.append(name)
            except OSError:
                pass
    try:
        state_file().unlink()
    except OSError:
        pass
    return removed


# --------------------------------------------------------------------------- #
# Linux
# --------------------------------------------------------------------------- #


def _install_linux(language: str) -> list[str]:
    lang = resolve_language(language)
    installed: list[str] = []

    # Nautilus
    nautilus_dir().mkdir(parents=True, exist_ok=True)
    # Remove any existing DiffAnyDoc script first
    for p in nautilus_dir().iterdir():
        if p.is_file():
            try:
                if "Installed by DiffAnyDoc" in p.read_text(encoding="utf-8"):
                    p.unlink()
            except Exception:
                pass
    nautilus_target = nautilus_dir() / current_label(lang)
    nautilus_target.write_text(nautilus_script(lang), encoding="utf-8")
    nautilus_target.chmod(0o755)
    installed.append(str(nautilus_target))

    # Nemo
    nemo_dir().mkdir(parents=True, exist_ok=True)
    # Clean up old 3-action files
    for slot in ("compare", "left", "right"):
        try:
            _nemo_path(slot).unlink()
        except OSError:
            pass
    nemo_target = _nemo_single_path()
    nemo_target.write_text(nemo_action(lang), encoding="utf-8")
    installed.append(str(nemo_target))

    # Dolphin
    dolphin_dir().mkdir(parents=True, exist_ok=True)
    service = dolphin_dir() / _DOLPHIN_FILE
    service.write_text(dolphin_service(lang), encoding="utf-8")
    installed.append(str(service))

    return installed


def _uninstall_linux() -> list[str]:
    removed: list[str] = []
    candidates: set[Path] = {
        dolphin_dir() / _DOLPHIN_FILE,
        _nemo_single_path(),
        _nemo_path("compare"),
        _nemo_path("left"),
        _nemo_path("right"),
    }
    # Nautilus scripts cleanup
    if nautilus_dir().is_dir():
        for p in nautilus_dir().iterdir():
            if p.is_file():
                try:
                    if "Installed by DiffAnyDoc" in p.read_text(encoding="utf-8"):
                        candidates.add(p)
                except Exception:
                    pass
    for language in available_languages():
        for slot in ("compare", "left", "right"):
            candidates.add(_nautilus_path(slot, language))
        candidates.add(nautilus_dir() / t("integrate.selectLeft", language))

    for path in sorted(candidates):
        try:
            path.unlink()
            removed.append(str(path))
        except FileNotFoundError:
            pass

    try:
        state_file().unlink()
    except OSError:
        pass
    return removed
