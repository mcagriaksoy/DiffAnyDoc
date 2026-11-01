"""Small, dependency-free translation layer.

Translations live in ``locales/<lang>.json`` so the UI (fetched over HTTP), the
HTML report and the CLI all read the same catalogue. Adding a language means
adding one JSON file — no code change.

English is always the default. The system locale is deliberately ignored so a
fresh install looks the same on every machine; users opt in to another language
with ``--lang``, ``DIFFANYDOC_LANG`` or the in-app language menu.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

LOCALE_DIR = Path(__file__).parent / "locales"
DEFAULT_LANGUAGE = "en"


@lru_cache(maxsize=None)
def catalogue(language: str) -> dict[str, str]:
    path = LOCALE_DIR / f"{language}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def available_languages() -> list[str]:
    return sorted(path.stem for path in LOCALE_DIR.glob("*.json"))


def resolve_language(requested: str | None = None) -> str:
    """Pick a supported language from an explicit request or env value.

    Falls back to English rather than the system locale: the product ships with
    English as its default and other languages are an explicit choice.
    """
    candidates: list[str] = []
    if requested:
        candidates.append(requested)
    env = os.environ.get("DIFFANYDOC_LANG")
    if env:
        candidates.append(env)

    supported = set(available_languages())
    for candidate in candidates:
        base = candidate.replace("-", "_").split("_")[0].strip().lower()
        if base in supported:
            return base
    return DEFAULT_LANGUAGE


def translate(key: str, language: str | None = None, **values: Any) -> str:
    """Look up ``key``, falling back to English and finally to the key itself."""
    lang = resolve_language(language)
    text = catalogue(lang).get(key)
    if text is None:
        text = catalogue(DEFAULT_LANGUAGE).get(key, key)
    if not values:
        return text
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


#: Short alias used across the codebase.
t = translate


def strings(language: str | None = None) -> dict[str, str]:
    """Full catalogue for one language, with English filling any gaps."""
    lang = resolve_language(language)
    merged = dict(catalogue(DEFAULT_LANGUAGE))
    merged.update(catalogue(lang))
    return merged
