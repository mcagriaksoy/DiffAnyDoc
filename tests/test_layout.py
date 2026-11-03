"""Reflow, hyphenation, folding, page alignment and change geometry."""

from __future__ import annotations

from pathlib import Path

from diffanydoc.core.adapters import load
from diffanydoc.core.diff import DiffOptions, change_rects, compare, fold_equal_runs
from diffanydoc.core.diff.align import align_pages
from diffanydoc.core.layout import make_line, merge_hyphenation, reflow
from diffanydoc.core.model import Document, Page, Row

from .pdfgen import write_pdf

PARAGRAPH = [
    "The Supplier shall deliver the goods described in Annex A to the",
    "premises of the Customer no later than thirty days after signature,",
    "and shall bear all costs of transport, insurance and customs until",
    "the goods have been accepted in writing by the Customer.",
]
EDITED = [
    "The Supplier shall deliver the new goods described in Annex A to",
    "the premises of the Customer no later than forty days after",
    "signature, and shall bear all costs of transport, insurance and",
    "customs until the goods have been accepted in writing by the",
    "Customer.",
]


def test_hyphenation_merge_does_not_shift_following_lines() -> None:
    blocks = [
        make_line([("an", (0, 0, 10, 10)), ("inter-", (12, 0, 40, 10))], 0),
        make_line([("national", (0, 12, 40, 22)), ("deal", (42, 12, 60, 22))], 0),
        make_line([("line", (0, 24, 20, 34)), ("three", (22, 24, 50, 34))], 0),
        make_line([("line", (0, 36, 20, 46)), ("four", (22, 36, 50, 46))], 0),
    ]
    merged = merge_hyphenation(blocks)
    assert [b.text for b in merged] == ["an international deal", "line three", "line four"]
    # Both halves of the hyphenated word keep a box on the page.
    word = [s for s in merged[0].spans if merged[0].text[s.start : s.end] in ("inter", "national")]
    assert len(word) == 2


def test_reflow_joins_wrapped_lines_only(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "p.pdf", [["1. Delivery"] + PARAGRAPH + ["2. Price", "Fixed."]])
    page = load(path).pages[0]
    joined = reflow(page.blocks)
    texts = [b.text for b in joined]
    assert texts[0] == "1. Delivery"
    assert texts[1] == " ".join(PARAGRAPH)
    assert texts[2:] == ["2. Price", "Fixed."]
    # Every word keeps its own span with the right text.
    block = joined[1]
    assert all(block.text[s.start : s.end] for s in block.spans)
    assert len(block.spans) == len(" ".join(PARAGRAPH).split())


def test_reflow_turns_rewrapped_paragraph_into_one_precise_change(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "l.pdf", [PARAGRAPH])
    right = write_pdf(tmp_path / "r.pdf", [EDITED])

    by_line = compare(left, right, DiffOptions(fold_equal=False, reflow=False))
    assert by_line.change_count >= 4  # every re-wrapped line looks changed

    result = compare(left, right, DiffOptions(fold_equal=False))
    assert result.change_count == 1
    row = result.rows[0]
    inserted = [s.text.strip() for s in row.right_inline if s.kind == "insert"]
    deleted = [s.text.strip() for s in row.left_inline if s.kind == "delete"]
    assert inserted == ["new", "forty"]
    assert deleted == ["thirty"]


def test_change_rects_box_changed_words(tmp_path: Path) -> None:
    left = write_pdf(tmp_path / "l.pdf", [["Invoice 2024-001", "Total: 1000 EUR"]])
    right = write_pdf(tmp_path / "r.pdf", [["Invoice 2024-001", "Total: 1250 EUR"]])
    result = compare(left, right, DiffOptions(fold_equal=False))
    rects = change_rects(result)
    words = [r for r in rects["right"]["0"] if r["level"] == "word"]
    lines = [r for r in rects["right"]["0"] if r["level"] == "line"]
    assert [w["text"] for w in words] == ["1250"]
    assert len(lines) == 1
    assert lines[0]["x0"] < words[0]["x0"] and words[0]["x1"] < lines[0]["x1"]
    assert words[0]["row"] == 1


def test_byte_identical_fast_path(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "a.pdf", [["Same"]])
    copy = tmp_path / "b.pdf"
    copy.write_bytes(path.read_bytes())
    result = compare(path, copy)
    assert result.byte_identical and result.identical
    assert result.left_info.sha256 == result.right_info.sha256
    assert result.right_path == copy


def _rows(n: int, changed: set[int]) -> list[Row]:
    return [Row(kind="replace" if i in changed else "equal") for i in range(n)]


def test_folding_keeps_full_context_on_both_sides() -> None:
    rows = _rows(40, {20})
    for index, row in enumerate(rows):
        row.left_inline = [index]  # marker to identify rows
    folded = fold_equal_runs(rows, 3)
    kept = [r.left_inline[0] for r in folded if r.left_inline]
    assert kept == [17, 18, 19, 20, 21, 22, 23]
    assert folded[0].hidden_before == 17
    assert folded[-1].hidden_before == 16 and folded[-1].left is None


def test_folding_short_runs_are_kept() -> None:
    folded = fold_equal_runs(_rows(5, {2}), 3)
    assert len(folded) == 5 and all(r.hidden_before == 0 for r in folded)


def test_page_alignment_survives_edits_and_insertions(tmp_path: Path) -> None:
    def doc(pages: list[str]) -> Document:
        return Document(
            path=tmp_path / "x",
            kind="pdf",
            pages=[
                Page(index=i, blocks=[make_line([(w, (0, 0, 1, 1)) for w in text.split()], i)])
                for i, text in enumerate(pages)
            ],
        )

    base = [
        "alpha beta gamma delta epsilon zeta",
        "one two three four five six seven",
        "red green blue yellow purple orange",
    ]
    edited = [
        "alpha beta gamma delta epsilon eta",
        "completely new page about something else entirely",
        "one two three four five six eight",
        "red green blue yellow purple black",
    ]
    pairs = [(p.left, p.right) for p in align_pages(doc(base), doc(edited))]
    assert pairs == [(0, 0), (None, 1), (1, 2), (2, 3)]


def test_inserted_line_is_not_paired_with_its_neighbour(tmp_path: Path) -> None:
    left = tmp_path / "l.txt"
    right = tmp_path / "r.txt"
    left.write_text("Total amount: 1000 EUR\n", encoding="utf-8")
    right.write_text("Total VAT: 190 EUR\nTotal amount: 1000 EUR.\n", encoding="utf-8")
    result = compare(left, right, DiffOptions(fold_equal=False))
    assert [row.kind for row in result.rows] == ["insert", "replace"]
