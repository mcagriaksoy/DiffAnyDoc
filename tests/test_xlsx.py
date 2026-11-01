from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from diffanydoc.core.adapters import load
from diffanydoc.core.adapters.base import AdapterError
from diffanydoc.core.diff import DiffOptions, compare

from .xlsxgen import write_xlsx


@pytest.fixture
def xlsx_pair(tmp_path: Path) -> tuple[Path, Path]:
    left = write_xlsx(
        tmp_path / "left.xlsx",
        [
            (
                "Bütçe",
                [
                    ["Kalem", "Adet", "Fiyat"],
                    ["Danışmanlık", 10, 1000],
                    ["Destek", 5, 500],
                ],
            )
        ],
        title="Bütçe 2026",
    )
    right = write_xlsx(
        tmp_path / "right.xlsx",
        [
            (
                "Bütçe",
                [
                    ["Kalem", "Adet", "Fiyat"],
                    ["Danışmanlık", 12, 1000],
                    ["Destek", 5, 500],
                ],
            )
        ],
    )
    return left, right


def test_xlsx_adapter_reads_sheets_and_cells(xlsx_pair: tuple[Path, Path]) -> None:
    document = load(xlsx_pair[0])

    assert document.kind == "xlsx"
    assert document.page_count == 1
    assert document.meta["sheets"] == ["Bütçe"]
    assert document.meta["title"] == "Bütçe 2026"

    table = document.pages[0].blocks[0]
    assert table.kind == "table"
    assert [row.text for row in table.children] == [
        "Kalem | Adet | Fiyat",
        "Danışmanlık | 10 | 1000",
        "Destek | 5 | 500",
    ]
    assert [cell.text for cell in table.children[1].children] == [
        "Danışmanlık",
        "10",
        "1000",
    ]
    assert table.children[1].children[0].source_ref["col"] == "A"


def test_xlsx_formats_numbers_dates_and_booleans(tmp_path: Path) -> None:
    path = write_xlsx(
        tmp_path / "types.xlsx",
        [
            (
                "Types",
                [
                    ["Number", 1250.0],
                    ["Fraction", 1.5],
                    ["Date", date(2026, 1, 31)],
                    ["Flag", True],
                ],
            )
        ],
    )
    table = load(path).pages[0].blocks[0]
    rows = [row.text for row in table.children]
    assert rows == [
        "Number | 1250",
        "Fraction | 1.5",
        "Date | 2026-01-31",
        "Flag | TRUE",
    ]


def test_xlsx_multiple_sheets_become_pages(tmp_path: Path) -> None:
    path = write_xlsx(
        tmp_path / "multi.xlsx",
        [
            ("First", [["a", 1]]),
            ("Second", [["b", 2]]),
        ],
    )
    document = load(path)
    assert document.page_count == 2
    assert document.meta["sheets"] == ["First", "Second"]
    assert document.pages[1].blocks[0].children[0].text == "b | 2"


def test_xlsx_empty_cells_keep_column_position(tmp_path: Path) -> None:
    path = write_xlsx(
        tmp_path / "gaps.xlsx",
        [("Sheet1", [["A", None, "C"], [None, "B", None]])],
    )
    table = load(path).pages[0].blocks[0]
    assert [row.text for row in table.children] == ["A |  | C", " | B"]


def test_xlsx_rejects_files_that_are_not_spreadsheets(tmp_path: Path) -> None:
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a zip")
    with pytest.raises(AdapterError):
        load(broken)

    empty = tmp_path / "empty.xlsx"
    with zipfile.ZipFile(empty, "w") as package:
        package.writestr("xl/other.xml", "<x/>")
    with pytest.raises(AdapterError):
        load(empty)


def test_xlsx_changed_cell_is_highlighted_alone(
    xlsx_pair: tuple[Path, Path],
) -> None:
    result = compare(*xlsx_pair, DiffOptions(context=1))

    assert not result.identical
    changed = [row for row in result.rows if row.kind == "replace"]
    assert len(changed) == 1
    row = changed[0]
    assert row.left is not None and row.right is not None
    assert row.left.cells == ["Danışmanlık", "10", "1000"]
    assert row.right.cells == ["Danışmanlık", "12", "1000"]

    deleted = "".join(
        segment.text for segment in row.left_inline or [] if segment.kind == "delete"
    )
    inserted = "".join(
        segment.text for segment in row.right_inline or [] if segment.kind == "insert"
    )
    assert deleted == "10"
    assert inserted == "12"


def test_xlsx_inline_segments_reconstruct_rows(xlsx_pair: tuple[Path, Path]) -> None:
    result = compare(*xlsx_pair, DiffOptions(context=1))
    for row in result.rows:
        if row.kind != "replace" or row.left is None or row.right is None:
            continue
        assert "".join(seg.text for seg in row.left_inline or []) == row.left.text
        assert "".join(seg.text for seg in row.right_inline or []) == row.right.text


def test_xlsx_inserted_row_is_an_insert(tmp_path: Path) -> None:
    left = write_xlsx(tmp_path / "l.xlsx", [("S", [["A", 1], ["B", 2]])])
    right = write_xlsx(
        tmp_path / "r.xlsx", [("S", [["A", 1], ["C", 3], ["B", 2]])]
    )
    result = compare(left, right, DiffOptions(context=1))
    inserts = [row.right.text for row in result.rows if row.kind == "insert" and row.right]
    assert inserts == ["C | 3"]


def test_xlsx_identical_files_are_identical(xlsx_pair: tuple[Path, Path]) -> None:
    result = compare(xlsx_pair[0], xlsx_pair[0])
    assert result.identical
    assert result.stats.similarity == 1.0
