from __future__ import annotations

from pathlib import Path

import pytest

from diffanydoc.core.adapters import load
from diffanydoc.core.diff import DiffOptions, compare
from diffanydoc.core.normalize import normalize_line

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
