"""Recursive folder & directory tree comparison engine.

Fast checksum-based file matching, categorization, and cross-format comparison triggers.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .adapters import supported_extensions

FolderStatus = Literal["identical", "modified", "added", "removed"]

IGNORED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".DS_Store",
    "Thumbs.db",
    "__pycache__",
    ".venv",
    "node_modules",
}


@dataclass(slots=True)
class FolderItem:
    rel_path: str
    status: FolderStatus
    left_path: str | None = None
    right_path: str | None = None
    left_size: int | None = None
    right_size: int | None = None
    left_sha256: str | None = None
    right_sha256: str | None = None
    is_supported: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FolderDiffResult:
    left_path: str
    right_path: str
    items: list[FolderItem] = field(default_factory=list)
    identical_count: int = 0
    modified_count: int = 0
    added_count: int = 0
    removed_count: int = 0

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def identical(self) -> bool:
        return (
            self.modified_count == 0
            and self.added_count == 0
            and self.removed_count == 0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "left_path": self.left_path,
            "right_path": self.right_path,
            "items": [item.as_dict() for item in self.items],
            "identical_count": self.identical_count,
            "modified_count": self.modified_count,
            "added_count": self.added_count,
            "removed_count": self.removed_count,
            "total_count": self.total_count,
            "identical": self.identical,
        }


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compare_folders(
    left_dir: str | Path,
    right_dir: str | Path,
    ignore_hidden: bool = True,
) -> FolderDiffResult:
    """Recursively compare two directory trees."""
    l_root = Path(left_dir).resolve()
    r_root = Path(right_dir).resolve()
    if not l_root.is_dir() or not r_root.is_dir():
        raise NotADirectoryError(f"Both paths must be directories: {l_root}, {r_root}")

    supported = set(supported_extensions())

    def walk_dir(root: Path) -> dict[str, Path]:
        res: dict[str, Path] = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in IGNORED_NAMES and not (ignore_hidden and d.startswith("."))
            ]
            for f in filenames:
                if f in IGNORED_NAMES or (ignore_hidden and f.startswith(".")):
                    continue
                full = Path(dirpath) / f
                rel = full.relative_to(root).as_posix()
                res[rel] = full
        return res

    left_files = walk_dir(l_root)
    right_files = walk_dir(r_root)

    all_rel = sorted(set(left_files.keys()) | set(right_files.keys()))
    items: list[FolderItem] = []
    identical_cnt = 0
    modified_cnt = 0
    added_cnt = 0
    removed_cnt = 0

    for rel in all_rel:
        in_left = rel in left_files
        in_right = rel in right_files
        ext = Path(rel).suffix.lower()
        is_supp = ext in supported

        if in_left and in_right:
            lp = left_files[rel]
            rp = right_files[rel]
            l_sz = lp.stat().st_size
            r_sz = rp.stat().st_size
            if l_sz != r_sz:
                status: FolderStatus = "modified"
                l_h = _file_hash(lp)
                r_h = _file_hash(rp)
                modified_cnt += 1
            else:
                l_h = _file_hash(lp)
                r_h = _file_hash(rp)
                if l_h == r_h:
                    status = "identical"
                    identical_cnt += 1
                else:
                    status = "modified"
                    modified_cnt += 1
            items.append(
                FolderItem(
                    rel_path=rel,
                    status=status,
                    left_path=str(lp),
                    right_path=str(rp),
                    left_size=l_sz,
                    right_size=r_sz,
                    left_sha256=l_h,
                    right_sha256=r_h,
                    is_supported=is_supp,
                )
            )
        elif in_right:
            rp = right_files[rel]
            r_sz = rp.stat().st_size
            added_cnt += 1
            items.append(
                FolderItem(
                    rel_path=rel,
                    status="added",
                    right_path=str(rp),
                    right_size=r_sz,
                    right_sha256=_file_hash(rp),
                    is_supported=is_supp,
                )
            )
        else:
            lp = left_files[rel]
            l_sz = lp.stat().st_size
            removed_cnt += 1
            items.append(
                FolderItem(
                    rel_path=rel,
                    status="removed",
                    left_path=str(lp),
                    left_size=l_sz,
                    left_sha256=_file_hash(lp),
                    is_supported=is_supp,
                )
            )

    return FolderDiffResult(
        left_path=str(l_root),
        right_path=str(r_root),
        items=items,
        identical_count=identical_cnt,
        modified_count=modified_cnt,
        added_count=added_cnt,
        removed_count=removed_cnt,
    )
