"""Tests for move detection (TASK-22) and presentation adapters (.pptx/.odp, TASK-23)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from diffanydoc.core.adapters import load
from diffanydoc.core.diff.engine import DiffOptions, compare
from diffanydoc.core.model import Block, Document, Page


def test_move_detection_flags_moved_lines() -> None:
    left = Document(
        path=Path("a.txt"),
        kind="txt",
        pages=[
            Page(
                index=0,
                blocks=[
                    Block(text="First paragraph stays at the top."),
                    Block(text="This specific clause was moved to the bottom."),
                    Block(text="Middle paragraph remains here."),
                ],
            )
        ],
    )
    right = Document(
        path=Path("b.txt"),
        kind="txt",
        pages=[
            Page(
                index=0,
                blocks=[
                    Block(text="First paragraph stays at the top."),
                    Block(text="Middle paragraph remains here."),
                    Block(text="This specific clause was moved to the bottom."),
                ],
            )
        ],
    )
    result = compare(left, right, DiffOptions(fold_equal=False))
    moved_deletes = [r for r in result.rows if r.kind == "delete" and r.moved]
    moved_inserts = [r for r in result.rows if r.kind == "insert" and r.moved]
    assert len(moved_deletes) == 1
    assert len(moved_inserts) == 1
    assert moved_deletes[0].left is not None
    assert moved_inserts[0].right is not None
    assert moved_deletes[0].left.text == moved_inserts[0].right.text


def test_pptx_adapter_loads_slides_and_notes(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    slide1 = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody>"
        "<a:p><a:r><a:t>Quarterly Review</a:t></a:r></a:p>"
        "<a:p><a:r><a:t>Revenue grew 15%</a:t></a:r></a:p>"
        "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )
    notes1 = (
        '<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody>"
        "<a:p><a:r><a:t>Remember to highlight Q4.</a:t></a:r></a:p>"
        "</p:txBody></p:sp></p:spTree></p:cSld></p:notes>"
    )
    with zipfile.ZipFile(pptx, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide1)
        zf.writestr("ppt/notesSlides/notesSlide1.xml", notes1)

    doc = load(pptx)
    assert doc.kind == "pptx"
    assert doc.page_count == 1
    assert doc.pages[0].label == "Slide 1"
    texts = [b.text for b in doc.pages[0].blocks]
    assert "Quarterly Review" in texts
    assert "Revenue grew 15%" in texts
    assert "[Note] Remember to highlight Q4." in texts


def test_odp_adapter_loads_slides(tmp_path: Path) -> None:
    odp = tmp_path / "deck.odp"
    content = (
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        "<office:body><office:presentation>"
        '<draw:page draw:name="page1"><draw:frame><draw:text-box>'
        "<text:h>Roadmap 2026</text:h>"
        "<text:p>Launch v1.0</text:p>"
        "</draw:text-box></draw:frame></draw:page>"
        "</office:presentation></office:body></office:document-content>"
    )
    with zipfile.ZipFile(odp, "w") as zf:
        zf.writestr("content.xml", content)

    doc = load(odp)
    assert doc.kind == "odp"
    assert doc.page_count == 1
    assert doc.pages[0].label == "Slide 1"
    texts = [b.text for b in doc.pages[0].blocks]
    assert texts == ["Roadmap 2026", "Launch v1.0"]


def test_pdf_position_shifts_have_unbroken_sequential_ids_and_no_false_pairs() -> None:
    from diffanydoc.core.diff.geometry import change_rects

    left = Document(
        path=Path("cv_a.pdf"),
        kind="pdf",
        pages=[
            Page(
                index=0,
                width=595,
                height=842,
                blocks=[
                    Block(text="Irem Ay Aksoy", bbox=(120.0, 50.0, 260.0, 72.0)),
                    Block(
                        text="ayyiremm@gmail.com +905315923506 Istanbul, Turkey linkedin.com/in/irem-ay",
                        bbox=(60.0, 140.0, 480.0, 155.0),
                    ),
                    Block(text="Business Analyst", bbox=(40.0, 320.0, 160.0, 336.0)),
                    Block(text="DeFacto Technology", bbox=(40.0, 340.0, 180.0, 355.0)),
                    Block(text="EDUCATION", bbox=(310.0, 420.0, 390.0, 436.0)),
                ],
            )
        ],
    )
    right = Document(
        path=Path("cv_b.pdf"),
        kind="pdf",
        pages=[
            Page(
                index=0,
                width=595,
                height=842,
                blocks=[
                    Block(text="IREM AY AKSOY", bbox=(40.0, 42.0, 200.0, 64.0)),
                    Block(text="BUSINESS ANALYST", bbox=(40.0, 68.0, 190.0, 84.0)),
                    Block(
                        text="+90 531 592 35 06 | ayyiremm@gmail.com | Istanbul, Turkey | linkedin.com/in/irem-ay",
                        bbox=(40.0, 92.0, 500.0, 106.0),
                    ),
                    Block(
                        text="DeFacto Technology (Business Analyst) Mar 2022 - Jul 2025",
                        bbox=(40.0, 190.0, 520.0, 206.0),
                    ),
                    Block(
                        text="Participated in Agile/Scrum ceremonies, including backlog refinement and sprint planning.",
                        bbox=(48.0, 410.0, 520.0, 426.0),
                    ),
                ],
            )
        ],
    )
    result = compare(left, right, DiffOptions(fold_equal=False))
    rects = change_rects(result)
    left_shifts = [
        r for r in rects["left"].get("0", []) if r.get("kind") == "shift"
    ]
    right_shifts = [
        r for r in rects["right"].get("0", []) if r.get("kind") == "shift"
    ]
    left_ids = [r["shift_id"] for r in left_shifts]
    right_ids = [r["shift_id"] for r in right_shifts]
    assert left_ids == [1, 2, 3, 4]
    assert right_ids == [1, 2, 3, 4]
    # Unrelated "EDUCATION" must NOT be paired or assigned a shift_id with the Agile bullet point
    for r in left_shifts:
        assert "EDUCATION" not in r["text"]


def test_unchanged_lines_after_insertion_or_deletion_are_not_flagged_as_shifts() -> None:
    from diffanydoc.core.diff.geometry import change_rects

    left = Document(
        path=Path("doc_a.pdf"),
        kind="pdf",
        pages=[
            Page(
                index=0,
                width=595,
                height=842,
                blocks=[
                    Block(text="Header Clause", bbox=(50.0, 50.0, 250.0, 66.0)),
                    Block(text="Temporary paragraph removed in B.", bbox=(50.0, 80.0, 320.0, 96.0)),
                    Block(text="Footer Clause Remains Unchanged", bbox=(50.0, 110.0, 300.0, 126.0)),
                ],
            )
        ],
    )
    right = Document(
        path=Path("doc_b.pdf"),
        kind="pdf",
        pages=[
            Page(
                index=0,
                width=595,
                height=842,
                blocks=[
                    Block(text="Header Clause", bbox=(50.0, 50.0, 250.0, 66.0)),
                    Block(text="Footer Clause Remains Unchanged", bbox=(50.0, 80.0, 300.0, 96.0)),
                ],
            )
        ],
    )
    result = compare(left, right, DiffOptions(fold_equal=False))
    rects = change_rects(result)
    assert [r for r in rects["left"].get("0", []) if r.get("kind") == "shift"] == []
    assert [r for r in rects["right"].get("0", []) if r.get("kind") == "shift"] == []
