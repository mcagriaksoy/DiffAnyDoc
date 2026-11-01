"""Text normalisation shared by every adapter and the diff engine.

Comparison quality depends almost entirely on what happens here: PDF and DOCX
produce slightly different characters for the same glyph (ligatures, curly
quotes, non-breaking spaces) and an unfair diff is the number one source of
"why does it say this line changed?".
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_SOFT_HYPHEN = "\u00ad"
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)

#: Characters that mean the same thing but have different code points.
_CHAR_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2212": "-",  # minus sign
        "\u00a0": " ",  # no-break space
        "\u202f": " ",  # narrow no-break space
        "\u2007": " ",
        "\u2009": " ",
        "\u200a": " ",
        "\u2026": "...",
        "\u00df": "ss",  # only reached after NFKD folding of case
    }
)


def fold(text: str) -> str:
    """Unicode-normalise text without changing its visible meaning."""
    if not text:
        return ""
    out = unicodedata.normalize("NFKC", text)
    out = out.translate(_ZERO_WIDTH)
    out = out.replace(_SOFT_HYPHEN, "")
    return out.translate(_CHAR_MAP)


def normalize_line(
    text: str,
    *,
    case_sensitive: bool = True,
    collapse_whitespace: bool = True,
) -> str:
    """Produce the key used to decide whether two lines are equal."""
    out = fold(text)
    if collapse_whitespace:
        out = _WHITESPACE.sub(" ", out).strip()
    if not case_sensitive:
        out = out.casefold()
    return out


def join_hyphenated_lines(lines: list[str]) -> list[str]:
    """Undo PDF hyphenation: ``inter-`` + ``national`` -> ``international``.

    Only joins when the first part ends with a hyphen and the next part starts
    with a lowercase letter, which keeps real compounds intact often enough.
    """
    out: list[str] = []
    for line in lines:
        if (
            out
            and out[-1].endswith("-")
            and not out[-1].endswith("--")
            and line[:1].islower()
        ):
            out[-1] = out[-1][:-1] + line
        else:
            out.append(line)
    return out
