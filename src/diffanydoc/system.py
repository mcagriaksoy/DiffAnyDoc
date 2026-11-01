"""Platform integration (best effort, never fatal).

Currently only the system accent colour, which is what makes the app look like
part of the desktop instead of a web page in a frame.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from functools import lru_cache

#: GNOME 47+ accent names -> hex.
GNOME_ACCENTS = {
    "blue": "#3584e4",
    "teal": "#2190a4",
    "green": "#3a944a",
    "yellow": "#c88800",
    "orange": "#ed5b00",
    "red": "#e62d42",
    "pink": "#d56199",
    "purple": "#9141ac",
    "slate": "#6f8396",
}

FALLBACK_ACCENT = "#3584e4"


@lru_cache(maxsize=1)
def accent_color() -> str:
    """Return the desktop accent colour as ``#rrggbb``."""
    for probe in (_gnome_accent, _windows_accent, _kde_accent):
        try:
            value = probe()
        except Exception:  # noqa: BLE001 - desktop probes must never crash the app
            value = None
        if value:
            return value
    return FALLBACK_ACCENT


def _gnome_accent() -> str | None:
    if not shutil.which("gsettings"):
        return None
    result = subprocess.run(
        ["gsettings", "get", "org.gnome.desktop.interface", "accent-color"],
        capture_output=True,
        text=True,
        timeout=1.5,
    )
    if result.returncode != 0:
        return None
    name = result.stdout.strip().strip("'\"")
    return GNOME_ACCENTS.get(name)


def _windows_accent() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg  # noqa: PLC0415 - Windows only

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM"
    ) as key:
        value, _ = winreg.QueryValueEx(key, "ColorizationColor")
    value = int(value)
    red = (value >> 16) & 0xFF
    green = (value >> 8) & 0xFF
    blue = value & 0xFF
    return f"#{red:02x}{green:02x}{blue:02x}"


def _kde_accent() -> str | None:
    for tool in ("kreadconfig6", "kreadconfig5"):
        if not shutil.which(tool):
            continue
        result = subprocess.run(
            [tool, "--file", "kdeglobals", "--group", "General", "--key", "AccentColor"],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split(",")
        if len(parts) != 3:
            return None
        try:
            red, green, blue = (max(0, min(255, int(part))) for part in parts)
        except ValueError:
            return None
        return f"#{red:02x}{green:02x}{blue:02x}"
    return None
