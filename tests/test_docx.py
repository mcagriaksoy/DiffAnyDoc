from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from diffanydoc.core.adapters import load
from diffanydoc.core.adapters.base import AdapterError
from diffanydoc.core.diff import DiffOptions, compare

from .docxgen import write_docx


@pytest.fixture
def docx_pair(tmp_path: Path) -> tuple[Path, Path]:
    left = write_docx(
        tmp_path / "left.docx",
        [
            ("p", "Hizmet Sözleşmesi", "Heading1"),
            ("p", "Taraflar: Acme ve Beta"),
            (
                "table",
                [
                    ["Kalem", "Adet", "Fiyat"],
                    ["Danışmanlık", "10", "1000"],
                    ["Destek", "5", "500"],
                ],
            ),
            ("p", "Toplam 1500 EUR"),
        ],
        title="Sözleşme",
        creator="Acme",
    )
    right = write_docx(
        tmp_path / "right.docx",
        [
            ("p", "Hizmet Sözleşmesi", "Heading1"),
            ("p", "Taraflar: Acme ve Gama"),
            (
                "table",
                [
                    ["Kalem", "Adet", "Fiyat"],
                    ["Danışmanlık", "10", "1250"],
                    ["Destek", "5", "500"],
                ],
            ),
            ("p", "Toplam 1750 EUR"),
        ],
    )
    return left, right


def test_docx_adapter_reads_paragraphs_and_tables(docx_pair: tuple[Path, Path]) -> None:
    document = load(docx_pair[0])

    assert document.kind == "docx"
    assert document.page_count == 1
    assert document.meta["title"] == "Sözleşme"
    assert document.meta["creator"] == "Acme"

    blocks = document.pages[0].blocks
    assert [block.kind for block in blocks] == ["text", "text", "table", "text"]
    assert blocks[0].text == "Hizmet Sözleşmesi"
    assert blocks[0].style["heading"] is True

    table = blocks[2]
    assert [row.kind for row in table.children] == ["table_row"] * 3
    assert table.children[0].style["header"] is True
    assert [cell.text for cell in table.children[1].children] == [
        "Danışmanlık",
        "10",
        "1000",
    ]


def test_docx_page_breaks_split_pages(tmp_path: Path) -> None:
    path = write_docx(
        tmp_path / "pages.docx",
        [("p", "Page one"), ("pagebreak",), ("p", "Page two")],
    )
    document = load(path)
    assert document.page_count == 2
    assert document.pages[0].blocks[0].text == "Page one"
    assert document.pages[1].blocks[0].text == "Page two"


def test_docx_rejects_files_that_are_not_word_documents(tmp_path: Path) -> None:
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip")
    with pytest.raises(AdapterError):
        load(broken)

    empty = tmp_path / "empty.docx"
    with zipfile.ZipFile(empty, "w") as package:
        package.writestr("word/other.xml", "<x/>")
    with pytest.raises(AdapterError):
        load(empty)


def test_docx_paragraph_change_is_paired(docx_pair: tuple[Path, Path]) -> None:
    result = compare(*docx_pair, DiffOptions(context=1))

    assert not result.identical
    changed = [row for row in result.rows if row.kind == "replace"]
    assert any(
        row.left and "Beta" in row.left.text and row.right and "Gama" in row.right.text
        for row in changed
    )


def test_docx_table_rows_keep_cells(docx_pair: tuple[Path, Path]) -> None:
    result = compare(*docx_pair, DiffOptions(context=1))

    table_rows = [row for row in result.rows if row.left and row.left.cells]
    assert table_rows, "table rows should reach the diff engine"
    assert table_rows[0].left.cells == ["Kalem", "Adet", "Fiyat"]

    price = next(
        row
        for row in table_rows
        if row.left.cells and row.left.cells[0] == "Danışmanlık"
    )
    assert price.kind == "replace"
    assert price.left.cells == ["Danışmanlık", "10", "1000"]
    assert price.right.cells == ["Danışmanlık", "10", "1250"]

    # Only the price cell is marked as changed; the other cells stay equal.
    assert price.left_inline is not None
    changed_text = "".join(
        segment.text for segment in price.left_inline if segment.kind == "delete"
    )
    assert changed_text == "1000"
    unchanged = "".join(
        segment.text for segment in price.left_inline if segment.kind == "equal"
    )
    assert "Danışmanlık" in unchanged and "10" in unchanged


def test_docx_table_inline_segments_reconstruct_rows(
    docx_pair: tuple[Path, Path],
) -> None:
    result = compare(*docx_pair, DiffOptions(context=1))
    for row in result.rows:
        if row.kind != "replace" or row.left is None or row.right is None:
            continue
        left_text = "".join(segment.text for segment in row.left_inline or [])
        right_text = "".join(segment.text for segment in row.right_inline or [])
        assert left_text == row.left.text
        assert right_text == row.right.text


def test_docx_inserted_table_row_is_an_insert(tmp_path: Path) -> None:
    left = write_docx(
        tmp_path / "l.docx",
        [("table", [["Kalem", "Fiyat"], ["A", "10"], ["B", "20"]])],
    )
    right = write_docx(
        tmp_path / "r.docx",
        [("table", [["Kalem", "Fiyat"], ["A", "10"], ["C", "30"], ["B", "20"]])],
    )
    result = compare(left, right, DiffOptions(context=1))
    inserts = [row.right for row in result.rows if row.kind == "insert"]
    assert [line.text for line in inserts if line] == ["C | 30"]


def test_docx_identical_files_are_identical(docx_pair: tuple[Path, Path]) -> None:
    result = compare(docx_pair[0], docx_pair[0])
    assert result.identical
    assert result.stats.similarity == 1.0
