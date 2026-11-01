from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffanydoc import i18n
from diffanydoc.cli import main
from diffanydoc.core.diff import compare
from diffanydoc.core.report.html import render_html


def _catalogue(language: str) -> dict[str, str]:
    return json.loads((i18n.LOCALE_DIR / f"{language}.json").read_text(encoding="utf-8"))


def test_english_and_turkish_define_the_same_keys() -> None:
    english = set(_catalogue("en"))
    turkish = set(_catalogue("tr"))
    assert english - turkish == set(), "eksik Türkçe anahtarlar"
    assert turkish - english == set(), "fazladan Türkçe anahtarlar"


def test_every_value_is_non_empty() -> None:
    for language in i18n.available_languages():
        for key, value in _catalogue(language).items():
            assert value.strip(), f"{language}:{key} boş"


def test_placeholders_match_across_languages() -> None:
    def placeholders(text: str) -> set[str]:
        import re

        return set(re.findall(r"\{(\w+)\}", text))

    english = _catalogue("en")
    for language in i18n.available_languages():
        catalogue = _catalogue(language)
        for key, value in catalogue.items():
            assert placeholders(value) == placeholders(english[key]), f"{language}:{key}"


def test_resolve_language_accepts_regional_tags() -> None:
    assert i18n.resolve_language("tr") == "tr"
    assert i18n.resolve_language("tr_TR.UTF-8") == "tr"
    assert i18n.resolve_language("en-GB") == "en"
    assert i18n.resolve_language("klingon") == i18n.DEFAULT_LANGUAGE
    assert i18n.resolve_language(None) == "en"


def test_system_locale_never_changes_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    monkeypatch.setenv("LC_ALL", "tr_TR.UTF-8")
    monkeypatch.delenv("DIFFANYDOC_LANG", raising=False)
    assert i18n.resolve_language(None) == "en"


def test_explicit_env_language_still_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIFFANYDOC_LANG", "tr")
    assert i18n.resolve_language(None) == "tr"
    assert i18n.resolve_language("en") == "en"


def test_translate_falls_back_to_english_then_key() -> None:
    assert i18n.t("stats.added", "tr") == "eklendi"
    assert i18n.t("stats.added", "xx") == "added"
    assert i18n.t("no.such.key", "tr") == "no.such.key"


def test_translate_substitutes_named_values() -> None:
    assert i18n.t("meta.pages", "en", n=3) == "3 pages"
    assert i18n.t("meta.pages", "tr", n=3) == "3 sayfa"


def test_strings_merges_english_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    merged = i18n.strings("tr")
    assert merged["report.similarity"] == "Benzerlik"
    assert "report.similarity" in i18n.strings("en")


def test_html_report_language_switches(tmp_path: Path) -> None:
    left = tmp_path / "a.txt"
    right = tmp_path / "b.txt"
    left.write_text("Total: 100\n", encoding="utf-8")
    right.write_text("Total: 120\n", encoding="utf-8")
    result = compare(left, right)

    english = render_html(result, language="en")
    turkish = render_html(result, language="tr")

    assert '<html lang="en">' in english and "Similarity" in english
    assert '<html lang="tr">' in turkish and "Benzerlik" in turkish
    assert "Benzerlik" not in english


def test_cli_output_language(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    left = tmp_path / "a.txt"
    right = tmp_path / "b.txt"
    left.write_text("bir\n", encoding="utf-8")
    right.write_text("iki\n", encoding="utf-8")

    assert main(["--lang", "en", "diff", str(left), str(right)]) == 0
    assert "similarity" in capsys.readouterr().out

    assert main(["--lang", "tr", "diff", str(left), str(right)]) == 0
    assert "benzerlik" in capsys.readouterr().out


def test_i18n_api_endpoints() -> None:
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from diffanydoc.web.server import create_app

    client = TestClient(create_app())
    languages = client.get("/api/i18n/languages").json()
    assert {"en", "tr"} <= set(languages["languages"])

    catalog = client.get("/api/i18n/tr").json()
    assert catalog["language"] == "tr"
    assert catalog["strings"]["stats.added"] == "eklendi"

    fallback = client.get("/api/i18n/de").json()
    assert fallback["language"] == i18n.DEFAULT_LANGUAGE
