"""DOCX, XLSX and CSV adapters and the table-aware parts of the engine."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from diffanydoc.core.adapters import AdapterError, load
from diffanydoc.core.adapters.xlsx import format_value
from diffanydoc.core.diff import DiffOptions, compare

from .officegen import delete, footnote_ref, ins, para, run, table, write_docx, write_xlsx

FULL = DiffOptions(fold_equal=False)


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #


def test_docx_paragraphs_headings_and_numbering(tmp_path: Path) -> None:
    path = write_docx(
        tmp_path / "a.docx",
        [
            para("Agreement", style="Heading1"),
            para("Parties", num=(1, 0)),
            para("Buyer", num=(1, 1)),
            para("Seller", num=(1, 1)),
            para("Payment", num=(1, 0)),
        ],
    )
    document = load(path)
    assert document.kind == "docx"
    body = document.pages[0]
    assert body.label == "section:body"
    texts = [b.text for b in body.blocks]
    assert texts == ["Agreement", "Parties", "Buyer", "Seller", "Payment"]
    assert body.blocks[0].style["heading"] == 1
    assert [b.style.get("list") for b in body.blocks[1:]] == ["1.", "1.1.", "1.2.", "2."]


def test_docx_numbering_is_not_compared(tmp_path: Path) -> None:
    """Inserting a clause renumbers the rest; only the new clause is a change."""
    left = write_docx(
        tmp_path / "l.docx",
        [para("Scope", num=(1, 0)), para("Price", num=(1, 0)), para("Term", num=(1, 0))],
    )
    right = write_docx(
        tmp_path / "r.docx",
        [
            para("Scope", num=(1, 0)),
            para("Delivery", num=(1, 0)),
            para("Price", num=(1, 0)),
            para("Term", num=(1, 0)),
        ],
    )
    result = compare(left, right, FULL)
    assert [row.kind for row in result.rows] == ["equal", "insert", "equal", "equal"]
    assert result.rows[2].right.style["list"] == "3."


def test_docx_tracked_changes_use_final_text(tmp_path: Path) -> None:
    path = write_docx(
        tmp_path / "tracked.docx",
        [para(run("Fee: "), delete("1000"), ins("1250"), run(" EUR"))],
    )
    document = load(path)
    assert document.pages[0].blocks[0].text == "Fee: 1250 EUR"
    assert document.meta["tracked_changes"] == {"insertions": 1, "deletions": 1}
    assert any(w["code"] == "tracked_changes" for w in document.warnings)


def test_docx_tables_headers_and_footnotes(tmp_path: Path) -> None:
    path = write_docx(
        tmp_path / "t.docx",
        [
            para(run("See note"), footnote_ref(2)),
            table([["Item", "Price"], ["Licence", "1000"]]),
        ],
        header="Confidential",
        footnotes={2: "Prices exclude VAT."},
    )
    document = load(path)
    body, headers, notes = document.pages
    assert body.blocks[0].text == "See note[1]"
    assert body.blocks[1].cells == ["Item", "Price"]
    assert body.blocks[2].cells == ["Licence", "1000"]
    assert headers.label == "section:headers" and headers.blocks[0].text == "Confidential"
    assert notes.label == "section:footnotes"
    assert notes.blocks[0].text == "Prices exclude VAT."
    assert notes.blocks[0].style["list"] == "[1]"


def test_docx_table_change_is_reported_per_cell(tmp_path: Path) -> None:
    left = write_docx(tmp_path / "l.docx", [table([["Item", "Qty", "Price"], ["Licence", "1", "1000"]])])
    right = write_docx(tmp_path / "r.docx", [table([["Item", "Qty", "Price"], ["Licence", "1", "1250"]])])
    result = compare(left, right, FULL)
    changed = [row for row in result.rows if row.kind == "replace"]
    assert len(changed) == 1
    cells = changed[0].cells
    assert [c.kind for c in cells] == ["equal", "equal", "replace"]
    assert (cells[2].left, cells[2].right) == ("1000", "1250")
    # Row-level inline segments still reconstruct the row text exactly.
    assert "".join(s.text for s in changed[0].left_inline) == changed[0].left.text
    assert "".join(s.text for s in changed[0].right_inline) == changed[0].right.text


def test_docx_formatting_changes_are_opt_in(tmp_path: Path) -> None:
    left = write_docx(tmp_path / "l.docx", [para(run("Total "), run("1000 EUR"))])
    right = write_docx(tmp_path / "r.docx", [para(run("Total "), run("1000 EUR", bold=True))])
    assert compare(left, right, FULL).identical
    result = compare(left, right, DiffOptions(fold_equal=False, compare_formatting=True))
    assert not result.identical
    assert result.rows[0].format_changes == ["bold"]
    assert result.stats.formatting == 1


def test_broken_docx_raises_adapter_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    with pytest.raises(AdapterError):
        load(path)


# --------------------------------------------------------------------------- #
# XLSX
# --------------------------------------------------------------------------- #


def test_xlsx_sheets_rows_and_columns(tmp_path: Path) -> None:
    path = write_xlsx(
        tmp_path / "a.xlsx",
        {"Budget": [["Item", "Q1"], ["Rent", 1000], [None, None], ["Staff", 5000.0]], "Notes": [["ok"]]},
    )
    document = load(path)
    assert document.kind == "xlsx"
    assert [p.label for p in document.pages] == ["Budget", "Notes"]
    budget = document.pages[0].blocks
    assert [b.label for b in budget] == ["1", "2", "4"]  # empty row skipped, numbers kept
    assert budget[2].cells == ["Staff", "5000"]
    assert budget[2].style["columns"] == ["A", "B"]


def test_xlsx_inserted_row_and_changed_cell(tmp_path: Path) -> None:
    left = write_xlsx(tmp_path / "l.xlsx", {"S": [["Item", "Q1", "Q2"], ["Rent", 1000, 1000], ["Staff", 5000, 5200]]})
    right = write_xlsx(
        tmp_path / "r.xlsx",
        {"S": [["Item", "Q1", "Q2"], ["Rent", 1000, 1000], ["Travel", 300, 200], ["Staff", 5000, 5300]]},
    )
    result = compare(left, right, FULL)
    assert [row.kind for row in result.rows] == ["equal", "equal", "insert", "replace"]
    staff = result.rows[3]
    assert (staff.left.label, staff.right.label) == ("3", "4")
    changed = [c for c in staff.cells if c.kind != "equal"]
    assert len(changed) == 1
    assert (changed[0].left_column, changed[0].left, changed[0].right) == ("C", "5200", "5300")


def test_xlsx_sheets_are_matched_by_name(tmp_path: Path) -> None:
    left = write_xlsx(tmp_path / "l.xlsx", {"A": [["x"]], "B": [["y"]]})
    right = write_xlsx(tmp_path / "r.xlsx", {"New": [["n"]], "A": [["x"]], "B": [["y2"]]})
    result = compare(left, right, FULL)
    pairs = [(p.left, p.right) for p in result.page_map]
    assert pairs == [(None, 0), (0, 1), (1, 2)]


def test_xlsx_format_value() -> None:
    assert format_value(1250.0) == "1250"
    assert format_value(0.1, "General") == "0.1"
    assert format_value(0.155, "0.0%") == "15.5%"
    assert format_value(True) == "TRUE"
    assert format_value(dt.datetime(2024, 5, 1)) == "2024-05-01"
    assert format_value(None) == ""


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #


def test_csv_is_compared_per_cell(tmp_path: Path) -> None:
    left = tmp_path / "l.csv"
    right = tmp_path / "r.csv"
    left.write_text("id;name;amount\n1;Acme;100\n2;Beta;200\n", encoding="utf-8")
    right.write_text("id;name;amount\n1;Acme;100\n2;Beta;250\n", encoding="utf-8")
    result = compare(left, right, FULL)
    changed = [row for row in result.rows if row.kind == "replace"]
    assert len(changed) == 1
    assert [c.kind for c in changed[0].cells] == ["equal", "equal", "replace"]
    assert changed[0].left.label == "3"
