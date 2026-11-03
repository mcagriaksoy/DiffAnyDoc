"""Excel (.xlsx) adapter using openpyxl (MIT).

Every worksheet is a page labelled with the sheet name, every non-empty row a
table block whose cells carry their column letters. The engine aligns rows
(so inserting a row does not shift every following row into a change) and then
cells, and reports changes as ``Sheet!C12``.

Cell text is the *displayed value*: the cached result for formulas, with
percentages and dates formatted the way a reader sees them. A formula with no
cached result (a file saved by a tool that does not calculate) falls back to
the formula text.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

from ..model import Block, Document, Page
from .base import AdapterError, LoadOptions

#: Stop reading a sheet after this many rows; reported as a warning.
MAX_ROWS = 200_000


class XlsxAdapter:
    name = "xlsx"
    extensions = (".xlsx", ".xlsm", ".xltx", ".xltm")

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def load(self, path: Path, options: LoadOptions | None = None) -> Document:
        try:
            import openpyxl
            from openpyxl.utils import get_column_letter
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise AdapterError("openpyxl is not installed: pip install openpyxl") from exc

        try:
            values = openpyxl.load_workbook(path, read_only=True, data_only=True)
            formulas = openpyxl.load_workbook(path, read_only=True, data_only=False)
        except Exception as exc:  # openpyxl raises many error types
            raise AdapterError(f"cannot read Excel file {path.name!r}: {exc}") from exc

        pages: list[Page] = []
        warnings: list[dict[str, Any]] = []
        hidden: list[str] = []
        formula_cells = 0
        try:
            for index, name in enumerate(values.sheetnames):
                sheet = values[name]
                formula_sheet = formulas[name]
                if getattr(sheet, "sheet_state", "visible") != "visible":
                    hidden.append(name)
                blocks: list[Block] = []
                truncated = False
                rows = zip(
                    sheet.iter_rows(values_only=False),
                    formula_sheet.iter_rows(values_only=True),
                )
                for row_index, (cells, raw) in enumerate(rows, start=1):
                    if row_index > MAX_ROWS:
                        truncated = True
                        break
                    texts: list[str] = []
                    for position, cell in enumerate(cells):
                        value = getattr(cell, "value", None)
                        formula = raw[position] if position < len(raw) else None
                        is_formula = isinstance(formula, str) and formula.startswith("=")
                        if is_formula:
                            formula_cells += 1
                        if value is None and is_formula:
                            texts.append(str(formula))
                        else:
                            texts.append(
                                format_value(value, getattr(cell, "number_format", "General"))
                            )
                    while texts and not texts[-1].strip():
                        texts.pop()
                    if not texts:
                        continue
                    first_column = _first_column(cells)
                    columns = [
                        get_column_letter(first_column + offset) for offset in range(len(texts))
                    ]
                    blocks.append(
                        Block(
                            kind="text",
                            text=" | ".join(texts),
                            cells=texts,
                            label=str(row_index),
                            style={"columns": columns, "sheet": name},
                            source_ref={"sheet": name, "row": row_index},
                        )
                    )
                if truncated:
                    warnings.append({"code": "sheet_truncated", "sheet": name, "rows": MAX_ROWS})
                pages.append(Page(index=index, blocks=blocks, label=name))
        finally:
            values.close()
            formulas.close()

        meta: dict[str, Any] = {"sheets": len(pages), "formulas": formula_cells}
        if hidden:
            meta["hidden_sheets"] = hidden
        return Document(path=path, kind="xlsx", pages=pages, meta=meta, warnings=warnings)


def _first_column(cells: Any) -> int:
    for cell in cells:
        column = getattr(cell, "column", None)
        if isinstance(column, int):
            return column
    return 1


_DECIMALS = re.compile(r"0\.(0+)")


def format_value(value: Any, number_format: str | None = "General") -> str:
    """Render a cell value roughly the way Excel displays it."""
    if value is None:
        return ""
    fmt = number_format or "General"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, _dt.datetime):
        if value.time() == _dt.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, (_dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return str(value)
    if isinstance(value, (int, float)):
        if "%" in fmt:
            match = _DECIMALS.search(fmt)
            decimals = len(match.group(1)) if match else 0
            return f"{value * 100:.{decimals}f}%"
        if isinstance(value, float):
            if value.is_integer() and abs(value) < 1e15:
                return str(int(value))
            return format(value, ".15g")
        return str(value)
    return str(value).strip()
