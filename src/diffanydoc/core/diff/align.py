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


def _page_tokens(document: Document, index: int) -> list[str]:
    page = document.pages[index]
    lines: list[str] = []
    for block in page.blocks:
        if block.kind == "text":
            lines.append(normalize_line(block.text, case_sensitive=False))
        elif block.kind == "table":
            for row in block.children:
                lines.append(normalize_line(row.text, case_sensitive=False))
    return lines


def _page_similarity(left_tokens: list[str], right_tokens: list[str]) -> float:
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    # Cap token sequence comparison to avoid O(N^2) blowup on multi-thousand-row sheets
    a = left_tokens[:500]
    b = right_tokens[:500]
    return SequenceMatcher(None, a, b, autojunk=True).ratio()


def align_pages(left: Document, right: Document) -> list[PagePair]:
    """Map left pages to right pages by content similarity.

    Uses a longest-common-subsequence over exact page keys, then pairs the
    leftover pages in order and reports their real similarity. This is
    deliberately cheap; heavily reflowed pages are the known weak spot.
    """
    if left.page_count == 1 and right.page_count == 1:
        sim = _page_similarity(_page_tokens(left, 0), _page_tokens(right, 0))
        return [PagePair(left=0, right=0, similarity=sim)]

    left_tokens = [_page_tokens(left, i) for i in range(left.page_count)]
    right_tokens = [_page_tokens(right, i) for i in range(right.page_count)]
    left_keys = ["\n".join(t) for t in left_tokens]
    right_keys = ["\n".join(t) for t in right_tokens]
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
                similarity = _page_similarity(left_tokens[i], right_tokens[j])
            pairs.append(PagePair(left=i, right=j, similarity=similarity))
    return pairs


def page_count_mismatch(left: Document, right: Document) -> int:
    return abs(left.page_count - right.page_count)
