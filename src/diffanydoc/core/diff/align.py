"""Page alignment.

Comparing raw line streams is not enough: one inserted page makes every
following page look different. Aligning pages first keeps the diff honest and
gives the viewer a page map to drive side-by-side scrolling.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from itertools import zip_longest

from ..model import Document, PagePair
from ..normalize import normalize_line


def _page_key(document: Document, index: int) -> str:
    return normalize_line(document.pages[index].text(" "), case_sensitive=False)


def align_pages(left: Document, right: Document) -> list[PagePair]:
    """Map left pages to right pages by content similarity.

    Uses a longest-common-subsequence over exact page keys, then pairs the
    leftover pages in order and reports their real similarity. This is
    deliberately cheap; M2 replaces it with an alignment that also survives
    reflowed pages.
    """
    left_keys = [_page_key(left, i) for i in range(left.page_count)]
    right_keys = [_page_key(right, i) for i in range(right.page_count)]
    matcher = SequenceMatcher(None, left_keys, right_keys, autojunk=False)

    pairs: list[PagePair] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend(
                PagePair(left=i, right=j, similarity=1.0)
                for i, j in zip(range(i1, i2), range(j1, j2))
            )
            continue
        for i, j in zip_longest(range(i1, i2), range(j1, j2)):
            if i is None and j is None:  # pragma: no cover - defensive
                continue
            similarity = 0.0
            if i is not None and j is not None:
                similarity = SequenceMatcher(
                    None, left_keys[i], right_keys[j], autojunk=False
                ).ratio()
            pairs.append(PagePair(left=i, right=j, similarity=similarity))
    return pairs


def page_count_mismatch(left: Document, right: Document) -> int:
    return abs(left.page_count - right.page_count)
