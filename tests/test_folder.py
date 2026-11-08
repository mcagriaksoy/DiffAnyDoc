"""Tests for directory & folder comparison mode."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from diffanydoc.core.folder import compare_folders
from diffanydoc.web.server import create_app


def test_compare_folders_identical(tmp_path: Path) -> None:
    dir_a = tmp_path / "dir_a"
    dir_b = tmp_path / "dir_b"
    dir_a.mkdir()
    dir_b.mkdir()

    (dir_a / "file1.txt").write_text("Hello\nWorld\n", encoding="utf-8")
    (dir_b / "file1.txt").write_text("Hello\nWorld\n", encoding="utf-8")

    sub_a = dir_a / "sub"
    sub_b = dir_b / "sub"
    sub_a.mkdir()
    sub_b.mkdir()
    (sub_a / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (sub_b / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    res = compare_folders(dir_a, dir_b)

    assert res.identical is True
    assert res.total_count == 2
    assert res.identical_count == 2
    assert res.modified_count == 0
    assert res.added_count == 0
    assert res.removed_count == 0


def test_compare_folders_with_modifications_add_del(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    # Same file
    (dir_a / "same.txt").write_text("Unchanged\n", encoding="utf-8")
    (dir_b / "same.txt").write_text("Unchanged\n", encoding="utf-8")

    # Modified file
    (dir_a / "mod.txt").write_text("Original text\n", encoding="utf-8")
    (dir_b / "mod.txt").write_text("Modified text with new line\n", encoding="utf-8")

    # Removed file (only in A)
    (dir_a / "removed.txt").write_text("Old file\n", encoding="utf-8")

    # Added file (only in B)
    (dir_b / "added.txt").write_text("New file\n", encoding="utf-8")

    # Ignored directory (.git)
    (dir_a / ".git").mkdir()
    (dir_a / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    res = compare_folders(dir_a, dir_b)

    assert res.identical is False
    assert res.identical_count == 1
    assert res.modified_count == 1
    assert res.added_count == 1
    assert res.removed_count == 1
    assert res.total_count == 4

    items_by_path = {item.rel_path: item for item in res.items}
    assert items_by_path["same.txt"].status == "identical"
    assert items_by_path["mod.txt"].status == "modified"
    assert items_by_path["removed.txt"].status == "removed"
    assert items_by_path["added.txt"].status == "added"
    assert ".git/HEAD" not in items_by_path

    # Verify dictionary serialization
    d = res.as_dict()
    assert d["identical_count"] == 1
    assert d["modified_count"] == 1
    assert len(d["items"]) == 4


def test_web_api_compare_directories(tmp_path: Path) -> None:
    dir1 = tmp_path / "d1"
    dir2 = tmp_path / "d2"
    dir1.mkdir()
    dir2.mkdir()
    (dir1 / "f.txt").write_text("v1\n", encoding="utf-8")
    (dir2 / "f.txt").write_text("v2\n", encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    res = client.post(
        "/api/compare-directories",
        json={"left": str(dir1), "right": str(dir2)},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["identical_count"] == 0
    assert data["modified_count"] == 1
    assert data["total_count"] == 1
    assert data["items"][0]["rel_path"] == "f.txt"


def test_cli_diff_folders(tmp_path: Path) -> None:
    dir1 = tmp_path / "cli_d1"
    dir2 = tmp_path / "cli_d2"
    dir1.mkdir()
    dir2.mkdir()
    (dir1 / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (dir2 / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (dir2 / "beta.txt").write_text("beta\n", encoding="utf-8")

    cmd = [
        sys.executable,
        "-m",
        "diffanydoc.cli",
        "diff",
        str(dir1),
        str(dir2),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0
    out = proc.stdout
    assert "alpha.txt" not in out or "beta.txt" in out
    assert "beta.txt (added)" in out
