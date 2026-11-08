from __future__ import annotations

from pathlib import Path

import pytest

from diffanydoc.core.adapters import load
from diffanydoc.core.diff import DiffOptions, compare
from diffanydoc.core.normalize import normalize_line
from diffanydoc.core.report.html import render_html

from .pdfgen import write_pdf


@pytest.fixture
def text_pair(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "a.txt"
    right = tmp_path / "b.txt"
    left.write_text(
        "Sözleşme\n"
        "1. Taraflar\n"
        "Alıcı: Acme A.Ş.\n"
        "Satıcı: Beta Ltd.\n"
        "2. Bedel\n"
        "Toplam 10.000 TL.\n",
        encoding="utf-8",
    )
    right.write_text(
        "Sözleşme\n"
        "1. Taraflar\n"
        "Alıcı: Acme A.Ş.\n"
        "Satıcı: Gama Ltd.\n"
        "Ödeme 30 gün içinde yapılır.\n"
        "2. Bedel\n"
        "Toplam 12.500 TL.\n",
        encoding="utf-8",
    )
    return left, right


@pytest.fixture
def pdf_pair(tmp_path: Path) -> tuple[Path, Path]:
    left = write_pdf(
        tmp_path / "left.pdf",
        [["Invoice 2024-001", "Customer: Acme", "Total: 1000 EUR"]],
    )
    right = write_pdf(
        tmp_path / "right.pdf",
        [["Invoice 2024-001", "Customer: Acme", "Total: 1250 EUR"]],
    )
    return left, right


def test_normalize_ignores_typography_and_spacing() -> None:
    assert normalize_line("  “Merhaba”\u00a0 dünya ") == '"Merhaba" dünya'
    assert normalize_line("ABC", case_sensitive=False) == "abc"
    assert normalize_line("inter-\nactive") != normalize_line("interactive")


def test_identical_files_have_no_changes(text_pair: tuple[Path, Path]) -> None:
    left, _ = text_pair
    result = compare(left, left, DiffOptions(context=3))
    assert result.identical
    assert result.change_count == 0
    assert result.stats.similarity == 1.0


def test_changed_line_is_paired_not_split(text_pair: tuple[Path, Path]) -> None:
    result = compare(*text_pair, DiffOptions(context=1))
    kinds = [row.kind for row in result.rows]

    replaces = [row for row in result.rows if row.kind == "replace"]
    assert any(row.left and "Beta" in row.left.text for row in replaces)
    assert any(row.right and "Gama" in row.right.text for row in replaces)

    inserts = [row for row in result.rows if row.kind == "insert"]
    assert [row.right.text for row in inserts] == ["Ödeme 30 gün içinde yapılır."]
    assert "insert" in kinds
    assert result.stats.changed == 2
    assert result.stats.added == 1
    assert result.stats.removed == 0
    assert 0 < result.stats.similarity < 1


def test_removed_line_is_reported(text_pair: tuple[Path, Path]) -> None:
    result = compare(text_pair[1], text_pair[0], DiffOptions(context=1))
    deletes = [row.left.text for row in result.rows if row.kind == "delete"]
    assert deletes == ["Ödeme 30 gün içinde yapılır."]
    assert result.stats.removed == 1


def test_inline_segments_reconstruct_both_sides(text_pair: tuple[Path, Path]) -> None:
    result = compare(*text_pair, DiffOptions(context=1))
    for row in result.rows:
        if row.kind != "replace":
            continue
        left_text = "".join(segment.text for segment in row.left_inline or [])
        right_text = "".join(segment.text for segment in row.right_inline or [])
        assert left_text == row.left.text
        assert right_text == row.right.text


def test_case_insensitive_option(tmp_path: Path) -> None:
    left = tmp_path / "l.txt"
    right = tmp_path / "r.txt"
    left.write_text("Toplam Bedel\n", encoding="utf-8")
    right.write_text("toplam bedel\n", encoding="utf-8")
    assert not compare(left, right, DiffOptions()).identical
    assert compare(left, right, DiffOptions(case_sensitive=False)).identical


def test_pdf_adapter_extracts_lines(pdf_pair: tuple[Path, Path]) -> None:
    document = load(pdf_pair[0])
    assert document.kind == "pdf"
    assert document.page_count == 1
    texts = [block.text for block in document.pages[0].blocks]
    assert texts[0] == "Invoice 2024-001"
    assert "Total: 1000 EUR" in texts
    assert document.pages[0].blocks[0].bbox is not None


def test_pdf_diff_finds_amount_change(pdf_pair: tuple[Path, Path]) -> None:
    result = compare(*pdf_pair)
    assert not result.identical
    assert result.stats.changed == 1
    changed = [row for row in result.rows if row.kind == "replace"]
    assert changed and changed[0].left and "1000" in changed[0].left.text


def test_multipage_page_map(tmp_path: Path) -> None:
    left = write_pdf(
        tmp_path / "multi_l.pdf",
        [["Page one"], ["Page two"], ["Page three"]],
    )
    right = write_pdf(
        tmp_path / "multi_r.pdf",
        [["Page one"], ["Page two"], ["Page three"]],
    )
    result = compare(left, right)
    assert [(p.left, p.right) for p in result.page_map] == [(0, 0), (1, 1), (2, 2)]


def test_folding_keeps_context(tmp_path: Path) -> None:
    left = tmp_path / "fold_l.txt"
    right = tmp_path / "fold_r.txt"
    lines = [f"line {index}" for index in range(40)]
    left.write_text("\n".join(lines) + "\n", encoding="utf-8")
    changed = list(lines)
    changed[20] = "line 20 changed"
    right.write_text("\n".join(changed) + "\n", encoding="utf-8")

    result = compare(left, right, DiffOptions(context=2))
    hidden = sum(row.hidden_before for row in result.rows)
    assert hidden > 0
    assert len(result.rows) < len(lines)


def test_full_output_can_disable_folding(tmp_path: Path) -> None:
    left = tmp_path / "full_l.txt"
    right = tmp_path / "full_r.txt"
    lines = [f"line {index}" for index in range(20)]
    left.write_text("\n".join(lines) + "\n", encoding="utf-8")
    right.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    result = compare(left, right, DiffOptions(fold_equal=False))
    assert all(row.hidden_before == 0 for row in result.rows)


def test_whitespace_edits_render_as_minor_in_html(tmp_path: Path) -> None:
    left = tmp_path / "space-a.txt"
    right = tmp_path / "space-b.txt"
    left.write_text("alpha beta\n", encoding="utf-8")
    right.write_text("alpha  beta\n", encoding="utf-8")

    result = compare(left, right, DiffOptions(collapse_whitespace=False))
    report = render_html(result, language="en")

    assert '<del class="minor"> </del>' in report
    assert '<ins class="minor">  </ins>' in report
    assert "--diff-minor-strong" in report


def test_fast_checksum_skips_loading_identical_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = tmp_path / "same-a.txt"
    right = tmp_path / "same-b.txt"
    left.write_text("Merhaba Dünya\nSatır 2\n", encoding="utf-8")
    right.write_text("Merhaba Dünya\nSatır 2\n", encoding="utf-8")

    def forbidden_load(_path: Path):
        raise AssertionError("load() must not be called when SHA-256 checksums match")

    monkeypatch.setattr("diffanydoc.core.diff.engine.load", forbidden_load)
    result = compare(left, right)

    assert result.identical is True
    assert result.byte_identical is True
    assert result.left_sha256 is not None
    assert result.left_sha256 == result.right_sha256
    assert result.rows == []
    assert result.stats.similarity == 1.0


def test_fast_check_can_be_disabled_to_parse_rows(tmp_path: Path) -> None:
    left = tmp_path / "parse-a.txt"
    right = tmp_path / "parse-b.txt"
    left.write_text("Satır 1\nSatır 2\n", encoding="utf-8")
    right.write_text("Satır 1\nSatır 2\n", encoding="utf-8")

    result = compare(left, right, DiffOptions(fast_check=False, fold_equal=False))
    assert result.identical is True
    assert result.byte_identical is True
    assert len(result.rows) == 2


def test_pdf_table_extraction_and_cell_alignment(tmp_path: Path) -> None:
    left = write_pdf(
        tmp_path / "table-l.pdf",
        [["Invoice Summary"]],
        tables=[
            [
                (
                    72.0,
                    700.0,
                    [150.0, 80.0, 100.0],
                    24.0,
                    [
                        ["Item", "Qty", "Price"],
                        ["Consulting", "10", "1000"],
                        ["Support", "5", "500"],
                    ],
                )
            ]
        ],
    )
    right = write_pdf(
        tmp_path / "table-r.pdf",
        [["Invoice Summary"]],
        tables=[
            [
                (
                    72.0,
                    700.0,
                    [150.0, 80.0, 100.0],
                    24.0,
                    [
                        ["Item", "Qty", "Price"],
                        ["Consulting", "10", "1250"],
                        ["Support", "5", "500"],
                    ],
                )
            ]
        ],
    )

    doc = load(left)
    kinds = [b.kind for b in doc.pages[0].blocks]
    assert "table" in kinds

    result = compare(left, right, DiffOptions(context=1))
    assert not result.identical
    changed = [r for r in result.rows if r.kind == "replace"]
    assert len(changed) == 1
    row = changed[0]
    assert row.left is not None and row.right is not None
    assert row.left.cells == ["Consulting", "10", "1000"]
    assert row.right.cells == ["Consulting", "10", "1250"]
    deleted = "".join(
        seg.text for seg in (row.left_inline or []) if seg.kind == "delete"
    )
    inserted = "".join(
        seg.text for seg in (row.right_inline or []) if seg.kind == "insert"
    )
    assert deleted == "1000"
    assert inserted == "1250"


def test_large_csv_comparison_is_fast_and_aligns_cells(tmp_path: Path) -> None:
    import time

    left = tmp_path / "large-a.csv"
    right = tmp_path / "large-b.csv"
    rows_a = ["id,name,department,salary"] + [
        f"{i},Employee {i},Engineering,{5000 + i}" for i in range(1, 3001)
    ]
    rows_b = list(rows_a)
    rows_b[1500] = "1500,Employee 1500,Engineering,99999"

    left.write_text("\n".join(rows_a) + "\n", encoding="utf-8")
    right.write_text("\n".join(rows_b) + "\n", encoding="utf-8")

    t0 = time.monotonic()
    result = compare(left, right, DiffOptions(fold_equal=False))
    elapsed = time.monotonic() - t0

    assert elapsed < 1.5, f"3000-row CSV took too long: {elapsed:.2f}s"
    assert result.left_kind == "csv"
    assert result.stats.changed == 1
    # Auto-folding keeps the DOM payload small on 3000-line files
    assert len(result.rows) < 50
    changed = [r for r in result.rows if r.kind == "replace"]
    assert len(changed) == 1
    assert changed[0].left is not None and changed[0].left.cells == [
        "1500",
        "Employee 1500",
        "Engineering",
        "6500",
    ]
    assert changed[0].right is not None and changed[0].right.cells == [
        "1500",
        "Employee 1500",
        "Engineering",
        "99999",
    ]


def test_detailed_reading_and_vocabulary_metrics(tmp_path: Path) -> None:
    f1 = tmp_path / "doc1.txt"
    f2 = tmp_path / "doc2.txt"

    # doc1 has 10 words, doc2 has 12 words (2 added words, 1 changed word)
    f1.write_text("The quick brown fox jumps over the lazy sleeping dog.\n\nSecond paragraph.\n", encoding="utf-8")
    f2.write_text("The fast brown fox leaps over the lazy sleeping dog.\n\nSecond modified paragraph with extra words.\n", encoding="utf-8")

    result = compare(f1, f2, DiffOptions())
    stats = result.stats

    assert stats.left_words > 0
    assert stats.right_words > stats.left_words
    assert stats.left_chars > 0
    assert stats.right_chars > 0
    assert stats.left_reading_time_min > 0
    assert stats.words_added > 0
    assert stats.words_removed > 0
    assert 0 < stats.change_density <= 1.0

    d = stats.as_dict()
    assert "left_words" in d
    assert "right_words" in d
    assert "left_reading_time_min" in d
    assert "change_density" in d




