"""Align pages between documents.

Comparing raw line streams is not enough: one inserted page makes every
following page look different. Aligning pages first keeps the diff honest and
gives the viewer a page map to drive side-by-side scrolling.

Two passes:

1. exact matches (identical page text, or identical labels such as sheet
   names) anchor the alignment cheaply;
2. between anchors, a global alignment (Needleman–Wunsch) over word-set
   similarity pairs pages that were edited or reflowed, so an inserted page
   is reported as inserted instead of shifting every page after it.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import zip_longest

from ..model import Document, PagePair
from ..normalize import normalize_line

_WORDS = re.compile(r"\w+", re.UNICODE)
#: Below this similarity two pages are not considered the same page.
MATCH_THRESHOLD = 0.3


def _page_key(document: Document, index: int) -> str:
    return normalize_line(document.pages[index].text(" "), case_sensitive=False)


def _words(text: str) -> frozenset[str]:
    return frozenset(_WORDS.findall(text))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _labelled(document: Document) -> bool:
    return bool(document.pages) and all(page.label for page in document.pages)


def align_pages(left: Document, right: Document) -> list[PagePair]:
    """Map left pages to right pages by content similarity (or by label)."""
    left_text = [_page_key(left, i) for i in range(left.page_count)]
    right_text = [_page_key(right, i) for i in range(right.page_count)]
    left_words = [_words(text) for text in left_text]
    right_words = [_words(text) for text in right_text]

    by_label = _labelled(left) and _labelled(right)
    if by_label:
        left_keys = [str(page.label) for page in left.pages]
        right_keys = [str(page.label) for page in right.pages]
    else:
        if left_text == right_text:
            return [
                PagePair(left=i, right=i, similarity=1.0)
                for i in range(left.page_count)
            ]
        if left.page_count * right.page_count <= 250_000:
            return _align_block(
                list(range(left.page_count)),
                list(range(right.page_count)),
                left_words,
                right_words,
            )
        left_keys, right_keys = left_text, right_text

    matcher = SequenceMatcher(None, left_keys, right_keys, autojunk=False)
    pairs: list[PagePair] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                similarity = (
                    _jaccard(left_words[i], right_words[j])
                    if by_label and left_text[i] != right_text[j]
                    else 1.0
                )
                pairs.append(PagePair(left=i, right=j, similarity=similarity))
            continue
        pairs.extend(
            _align_block(
                list(range(i1, i2)), list(range(j1, j2)), left_words, right_words
            )
        )
    return pairs


def _align_block(
    left: list[int],
    right: list[int],
    left_words: list[frozenset[str]],
    right_words: list[frozenset[str]],
) -> list[PagePair]:
    """Optimal monotone pairing of two runs of pages."""
    if not left or not right:
        return [PagePair(left=i, right=None, similarity=0.0) for i in left] + [
            PagePair(left=None, right=j, similarity=0.0) for j in right
        ]

    n, m = len(left), len(right)
    similarity = [
        [_jaccard(left_words[i], right_words[j]) for j in right] for i in left
    ]
    # score[i][j]: best total for left[:i] vs right[:j]. A match earns
    # (similarity - threshold), so only pages that really correspond pair up.
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[0] * (m + 1) for _ in range(n + 1)]  # 1 diag, 2 up, 3 left
    for i in range(1, n + 1):
        move[i][0] = 2
    for j in range(1, m + 1):
        move[0][j] = 3
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sim = similarity[i - 1][j - 1]
            # Tiny positional tie-breaker so repeated/identical pages pair at matching offsets.
            tie = 1e-5 * (1.0 - abs(i / n - j / m)) if sim >= MATCH_THRESHOLD else 0.0
            diag = score[i - 1][j - 1] + sim - MATCH_THRESHOLD + tie
            up = score[i - 1][j]
            side = score[i][j - 1]
            best = max(diag, up, side)
            score[i][j] = best
            move[i][j] = 1 if best == diag and diag > max(up, side) else (2 if up >= side else 3)

    matches: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        step = move[i][j]
        if step == 1:
            matches.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif step == 2:
            i -= 1
        else:
            j -= 1
    matches.reverse()

    # Between two matched anchors, leftover pages on both sides are shown
    # side by side (a rewritten page is still "the same page" to a reader);
    # only a surplus on one side becomes an inserted or removed page.
    pairs: list[PagePair] = []
    previous = (-1, -1)
    for anchor in matches + [(n, m)]:
        gap_left = range(previous[0] + 1, anchor[0])
        gap_right = range(previous[1] + 1, anchor[1])
        for a, b in zip_longest(gap_left, gap_right):
            pairs.append(
                PagePair(
                    left=left[a] if a is not None else None,
                    right=right[b] if b is not None else None,
                    similarity=similarity[a][b] if a is not None and b is not None else 0.0,
                )
            )
        if anchor != (n, m):
            pairs.append(
                PagePair(
                    left=left[anchor[0]],
                    right=right[anchor[1]],
                    similarity=similarity[anchor[0]][anchor[1]],
                )
            )
        previous = anchor
    return pairs
