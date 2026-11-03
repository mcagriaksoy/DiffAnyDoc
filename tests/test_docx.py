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


def test_docx_reads_headers_footers_and_footnotes(tmp_path: Path) -> None:
    path = write_docx(tmp_path / "full.docx", [("p", "Gövde metni")])
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(path, "a") as package:
        package.writestr(
            "word/header1.xml",
            f'<w:hdr xmlns:w="{w_ns}"><w:p><w:r><w:t>Gizli Sözleşme</w:t></w:r></w:p></w:hdr>',
        )
        package.writestr(
            "word/footer1.xml",
            f'<w:ftr xmlns:w="{w_ns}"><w:p><w:r><w:t>Sayfa Altbilgisi</w:t></w:r></w:p></w:ftr>',
        )
        package.writestr(
            "word/footnotes.xml",
            f'<w:footnotes xmlns:w="{w_ns}">'
            '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:t>-</w:t></w:r></w:p></w:footnote>'
            '<w:footnote w:id="1"><w:p><w:r><w:t>Dipnot 1 açıklaması</w:t></w:r></w:p></w:footnote>'
            "</w:footnotes>",
        )

    doc = load(path)
    texts = [b.text for b in doc.pages[0].blocks]
    assert texts == [
        "Gizli Sözleşme",
        "Gövde metni",
        "Dipnot 1 açıklaması",
        "Sayfa Altbilgisi",
    ]


def test_docx_formatting_diff_detects_bold_and_size_changes(tmp_path: Path) -> None:
    left = tmp_path / "fmt-left.docx"
    right = tmp_path / "fmt-right.docx"
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    write_docx(left, [("p", "Madde 1: Gizlilik yükümlülüğü")])
    write_docx(right, [("p", "Madde 1: Gizlilik yükümlülüğü")])

    # Make the paragraph bold + 14pt (w:sz val="28") in right.docx
    with zipfile.ZipFile(right, "r") as zin:
        items = {name: zin.read(name) for name in zin.namelist()}
    items["word/document.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{w_ns}"><w:body>'
        '<w:p><w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr>'
        "<w:t>Madde 1: Gizlilik yükümlülüğü</w:t></w:r></w:p>"
        "<w:sectPr/></w:body></w:document>"
    ).encode("utf-8")
    with zipfile.ZipFile(right, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, content in items.items():
            zout.writestr(name, content)

    # Without compare_formatting, text is identical
    assert compare(left, right, DiffOptions(compare_formatting=False)).identical is True

    # With compare_formatting=True, style change is flagged as replace
    diff_fmt = compare(left, right, DiffOptions(compare_formatting=True))
    assert diff_fmt.identical is False
    assert diff_fmt.stats.changed == 1
    row = diff_fmt.rows[0]
    assert row.kind == "replace"
    assert row.right is not None
    assert "bold" in row.right.style.get("style_change", "")
    assert "14pt" in row.right.style.get("style_change", "")


def test_docx_long_paragraph_highlights_only_changed_words(tmp_path: Path) -> None:
    left_para = (
        "İşbu sözleşme kapsamında yüklenici firma, belirlenen tüm yazılım "
        "geliştirme ve bakım hizmetlerini 30 gün içerisinde eksiksiz olarak "
        "teslim etmeyi kabul ve taahhüt eder."
    )
    right_para = (
        "İşbu sözleşme kapsamında yüklenici firma, belirlenen tüm donanım "
        "kurulum ve bakım hizmetlerini 45 gün içerisinde eksiksiz olarak "
        "teslim etmeyi kabul ve taahhüt eder."
    )
    left = write_docx(tmp_path / "p-left.docx", [("p", left_para)])
    right = write_docx(tmp_path / "p-right.docx", [("p", right_para)])

    result = compare(left, right)
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.kind == "replace"
    deleted = [s.text.strip() for s in (row.left_inline or []) if s.kind == "delete" and s.text.strip()]
    inserted = [s.text.strip() for s in (row.right_inline or []) if s.kind == "insert" and s.text.strip()]
    equal_len = sum(len(s.text) for s in (row.left_inline or []) if s.kind == "equal")

    assert deleted == ["yazılım geliştirme", "30"]
    assert inserted == ["donanım kurulum", "45"]
    assert equal_len > len(left_para) * 0.75



