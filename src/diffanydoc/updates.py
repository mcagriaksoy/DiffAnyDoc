"""Update check against the project's GitHub releases.

Privacy first: nothing is sent automatically. The check runs only when the user
presses "Check for Updates", sends no identifiers (a plain GET with a generic
User-Agent) and only reads the public "latest release" record.

The download itself stays a user action: we link to the release page instead of
replacing the running binary, which keeps code signing and package managers
(winget, apt, Flatpak) in charge of installation.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__

REPOSITORY = "mcagriaksoy/DiffAnyDoc"
DEFAULT_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"


@dataclass(slots=True)
class UpdateInfo:
    current: str
    status: str  # "update", "latest", "no_releases", "error"
    latest: str | None = None
    url: str = RELEASES_PAGE
    published: str | None = None
    notes: str | None = None
    assets: list[dict[str, Any]] | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-.]?(alpha|beta|rc|dev|a|b)\.?(\d*))?")
_PRE_ORDER = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "rc": 3}


def parse_version(text: str) -> tuple[tuple[int, ...], tuple[int, int]]:
    """Comparable key: (release numbers, (pre-release rank, number)).

    A final release ranks above its pre-releases: 1.0rc1 < 1.0.
    """
    match = _VERSION.match(text.strip())
    if not match:
        return ((0,), (-1, 0))
    numbers = tuple(int(part) for part in match.group(1).split("."))
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers = numbers[:-1]
    if match.group(2):
        pre = (_PRE_ORDER[match.group(2)], int(match.group(3) or 0))
    else:
        pre = (9, 0)
    return numbers, pre


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def check(current: str = __version__, url: str | None = None, timeout: float = 6.0) -> UpdateInfo:
    url = url or os.environ.get("DIFFANYDOC_UPDATE_URL") or DEFAULT_URL
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"DiffAnyDoc/{current}",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return UpdateInfo(current=current, status="no_releases")
        return UpdateInfo(current=current, status="error", message=f"HTTP {exc.code}")
    except (URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return UpdateInfo(current=current, status="error", message=str(reason))

    tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if not tag:
        return UpdateInfo(current=current, status="no_releases")
    latest = tag.lstrip("v")
    assets = [
        {
            "name": asset.get("name"),
            "url": asset.get("browser_download_url"),
            "size": asset.get("size"),
        }
        for asset in payload.get("assets") or []
        if asset.get("browser_download_url")
    ]
    notes = payload.get("body")
    return UpdateInfo(
        current=current,
        status="update" if is_newer(latest, current) else "latest",
        latest=latest,
        url=str(payload.get("html_url") or RELEASES_PAGE),
        published=payload.get("published_at"),
        notes=notes[:4000] if isinstance(notes, str) else None,
        assets=assets,
    )
