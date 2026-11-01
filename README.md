# DiffAnyDoc

Desktop app that compares documents side by side: PDF, DOCX, XLSX and plain text.
It shows text differences and marks changed lines with boxes on PDF pages.

![DiffAnyDoc screenshot](docs/screenshot.png)

## Status

This repository contains **M0 + M1** in working order:

- Adapter layer for PDF and text files
- Line alignment plus word-level inline differences
- Page matching (inserting a page no longer makes every later page look changed)
- Self-contained HTML report and stable JSON output
- `diff`, `info`, `formats`, `serve`, `desktop`, `select`, `integrate` commands
- Web UI and a **native desktop window** (pywebview / GTK)
- 58 tests (`pytest`)

Not there yet: DOCX/XLSX adapters, OCR, table-cell diffing, visual (pixel) diff.

English is the default for the app, CLI messages and reports. Turkish ships as a
second locale and can be selected in the app, or with `--lang tr` /
`DIFFANYDOC_LANG=tr`; the system locale is not used to pick a language.

## Installation

System dependencies (Linux, for the native window):

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1 libgtk-3-0
```

Python side — the virtualenv must see system packages so it can load the GTK
bindings:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ".[dev,web,desktop]"
```

> `--system-site-packages` is only needed for the desktop shell on Linux;
> `PyGObject` cannot be built with pip, so the system `python3-gi` is used.
> Server and CLI usage do not need it.

> **No standalone executable yet.** `diffanydoc` is a console script inside the
> virtualenv. M5 adds PyInstaller builds: `DiffAnyDoc.exe` on Windows and an
> AppImage or `.deb` on Linux. The context-menu integration above also works
> from a source checkout.

## Usage

### Desktop

```bash
diffanydoc desktop                                # empty window
diffanydoc desktop old.pdf new.pdf                # compare on launch
diffanydoc desktop old.pdf new.pdf --debug        # webview developer tools
```

### App menu

The **⋯** button in the top right opens the overflow menu. Besides the
comparison actions (report, new comparison) it holds:

- **About DiffAnyDoc** — icon, version and a one-line summary
- **License Agreement** — the full license text in a scrollable dialog
- **Check for Updates** — reports the current version (network checks are TODO)

These open as in-app modal dialogs rather than a classic menu bar; there is one
toolbar per window, matching the GNOME/libadwaita pattern.

### App icon

`tools/make_icon.py` generates the icon (one document between back/forward
arrows, with a red/green diff line) into SVG, PNG and ICO:

```bash
.venv/bin/python tools/make_icon.py
```

Output goes to `src/diffanydoc/web/static/icon.svg`, `icon.png`,
`icon-32.png` and `icon.ico`. The SVG is the favicon and in-app brand mark, the
PNG is the GTK window icon, and the ICO is used by the Windows build.

### File-manager integration (left/right context menu)

```bash
diffanydoc integrate install      # add "Select as left/right file" entries
diffanydoc integrate uninstall    # remove them
```

The entries hand the chosen file to the running window, or open one if needed:

1. Right-click a file → **Select as left file (DiffAnyDoc)**
2. Right-click another file → **Select as right file (DiffAnyDoc)**

The two files are compared automatically. On Windows this uses per-user registry
entries (no administrator rights); on Windows 11 the entries may appear under
**Show more options**. On Linux both Nautilus scripts and a Dolphin/KDE service
menu are installed, because GNOME Files has no cross-desktop context-menu API.
Menu labels follow `--lang`, e.g. `diffanydoc --lang tr integrate install`.
Restart Nautilus once (`nautilus -q`) if the scripts do not show up immediately.

### Browser (local server / on-prem team use)

```bash
diffanydoc serve --port 8765
# http://127.0.0.1:8765
```

### Command line

```bash
diffanydoc diff a.pdf b.pdf                       # summary in the terminal
diffanydoc diff a.pdf b.pdf -o report.html        # HTML report
diffanydoc diff a.txt b.txt --format json         # machine-readable output
diffanydoc diff a.pdf b.pdf --fail-on-diff        # exit code 1 when different
diffanydoc info document.pdf
diffanydoc formats
diffanydoc select left a.pdf                      # hand a file to the running window
```

`--fail-on-diff` is designed for CI:

```bash
git config diff.diffanydoc.command 'diffanydoc diff --fail-on-diff $2 $5'
```

## Architecture

```
file ──> [adapter] ──> Document IR ──> [diff engine] ──> DiffResult ──> CLI / HTML / API / UI
```

The one rule: **formats are converted into a shared model, not into each other.**
That way a PDF and a DOCX can be compared by the same engine; adding a format
means writing an adapter, not a new diff algorithm.

```
src/diffanydoc/
  core/
    model.py          # Document / Page / Block + DiffResult / Row
    normalize.py      # NFKC, typography, soft hyphen, whitespace normalisation
    adapters/         # base.py (registry), pdf.py, text.py
    diff/             # align.py (pages), lines.py (lines + inline), engine.py
    report/           # html.py, json.py
  cli.py              # reference consumer of every feature
  web/                # FastAPI + build-free SPA
  desktop/            # pywebview shell (local API + native window)
```

The engine under `core/` knows nothing about Qt or HTTP, so the CLI, API and
desktop share the same code and the engine is tested separately.

### Diff layers

| Layer | Status | Note |
|---|---|---|
| Byte (sha256) | missing | fast path for identical files |
| Structure (docx XML, pdf objects) | planned | M3 |
| Text (line + word) | **done** | M0 |
| Page mapping | **done** | simple LCS; similarity-based in M2 |
| Visual (pixel) | planned | M2 |
| OCR layer | planned | M4, only when there is no text |

## Licensing strategy

Because the target is a commercial release, dependencies were chosen from
**permissive** licences:

| Package | Licence | Use |
|---|---|---|
| `pdfplumber` / `pdfminer.six` | MIT | PDF text + coordinates |
| `pypdfium2` | Apache-2.0 / BSD-3 | PDF rendering |
| `Pillow` | MIT-CMU | images |
| `fastapi` / `uvicorn` | MIT / BSD-3 | API |
| `pywebview` | BSD-3 | desktop shell |
| GTK / WebKit2GTK | LGPL | system webview (dynamic linking) |

Deliberately **not used**: PyMuPDF (AGPL), PyQt6 (GPL), parts of reportlab.
These would require extra licensing for a closed-source commercial release.

> ⚠️ The `LICENSE` file in the repository is still the GPL-3.0 text from the
> first commit and **must change before any release.** Suggested model: AGPL-3.0
> for the open-source repository plus a separate commercial licence for paying
> customers (dual licensing), or fully proprietary until 1.0. Do not publish
> before that decision.

## Roadmap

- **M0 — engine + CLI** ✅ IR, PDF/text adapters, line + inline diff, HTML/JSON report
- **M1 — viewer** ✅ web UI + native window, change boxes on PDF pages
- **M2 — visual diff** page-render comparison, tolerance, registration
- **M3 — DOCX/XLSX** structural diff, table-cell alignment
- **M4 — OCR** fallback layer for scanned PDFs + cache
- **M5 — distribution** PyInstaller/Tauri packaging, auto-update, licensing

## Tests

```bash
pytest
```

Test fixtures generate PDFs at runtime (`tests/pdfgen.py`); no binaries are kept
in the repository. Files under `samples/` are there for manual testing.

## Known limitations

- DOCX/XLSX are not supported yet → those files are read as plain text and give
  meaningless results.
- Scanned PDFs (no text layer) have no text to compare.
- Line-based alignment can be noisy when paragraphs are reflowed.
- Tables are read as single lines of text (no column alignment).
