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


def parse_version(tag: str) -> tuple[tuple[int, ...], int, int]:
    match = _VERSION.match(tag.strip())
    if not match:
        return ((), 0, 0)
    numbers = tuple(int(p) for p in match.group(1).split("."))
    pre_tag = match.group(2)
    pre_rank = _PRE_ORDER.get(pre_tag, 4) if pre_tag else 4
    pre_num = int(match.group(3)) if match.group(3) else 0
    return (numbers, pre_rank, pre_num)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def check_for_updates(
    endpoint: str | None = None,
    current: str = __version__,
    timeout: float = 4.0,
) -> UpdateInfo:
    url = endpoint or os.environ.get("DIFFANYDOC_UPDATE_URL") or DEFAULT_URL
    request = Request(
        url,
        headers={
            "User-Agent": f"DiffAnyDoc/{current}",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        if err.code == 404:
            return UpdateInfo(current=current, status="no_releases", message="No releases published yet.")
        return UpdateInfo(current=current, status="error", message=f"GitHub API error: {err.code}")
    except (URLError, TimeoutError, OSError) as err:
        return UpdateInfo(current=current, status="error", message=str(err))
    except Exception as err:
        return UpdateInfo(current=current, status="error", message=f"Failed to read update: {err}")

    tag = payload.get("tag_name", "").lstrip("v")
    html_url = payload.get("html_url") or RELEASES_PAGE
    notes = payload.get("body") or ""
    published = payload.get("published_at")
    assets = [
        {
            "name": a.get("name"),
            "size": a.get("size"),
            "download_url": a.get("browser_download_url"),
        }
        for a in payload.get("assets", [])
    ]

    if not tag:
        return UpdateInfo(current=current, status="no_releases")

    if is_newer(tag, current):
        return UpdateInfo(
            current=current,
            status="update",
            latest=tag,
            url=html_url,
            published=published,
            notes=notes,
            assets=assets,
        )
    return UpdateInfo(
        current=current,
        status="latest",
        latest=tag,
        url=html_url,
        published=published,
        notes=notes,
        assets=assets,
    )


check = check_for_updates
