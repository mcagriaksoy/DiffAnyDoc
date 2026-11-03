# DiffAnyDoc

Desktop app that compares documents side by side: PDF, Word, Excel, CSV,
images/scans and plain text. It shows what changed in the text — down to the
word and the table cell — boxes the changed words on the page, and compares the
rendered pages pixel by pixel for what text cannot show (stamps, signatures,
logos, scans).

![DiffAnyDoc screenshot](docs/screenshot.png)

## Status

All roadmap milestones (M0–M5) are implemented:

| | What you get |
|---|---|
| **Text diff** | line + word-level diff; paragraphs of a PDF are re-joined before comparing, so a re-wrapped paragraph shows only the words that changed |
| **PDF** | text with word coordinates; changed *words* boxed on the page; click a box to jump to the line |
| **Word (.docx)** | paragraphs, headings, automatic clause numbering (shown, not compared), tables cell by cell, headers/footers, footnotes, endnotes, comments, text boxes; tracked changes compared as accepted and reported |
| **Excel (.xlsx)** | every sheet, matched by name; rows aligned (an inserted row is one insertion), changes reported per cell (`C4: 5200 → 5300`); displayed values, percentages and dates |
| **CSV / TSV** | parsed as tables, so changes are per cell too |
| **Images & scans** | PNG, JPEG, TIFF (multi-page), BMP, WebP; OCR when Tesseract is installed |
| **Visual diff** | rendered pages registered and compared with a noise-tolerant pixel diff; changed areas boxed; red/green *Overlay* view |
| **OCR** | Tesseract for pages without a text layer, with a disk cache |
| **Formatting** | optional: bold/italic/underline/heading/style changes on otherwise equal text |
| **Reports** | self-contained HTML, stable JSON (format 2), terminal text; `--fail-on-diff` for CI |
| **Distribution** | PyInstaller bundles for Windows and Linux, release workflow, update check |

Not there yet: a signed installer (MSI/winget, Flatpak), macOS build, moved-block
detection, and the licence decision (see below).

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

> **Ready-made bundles** are built by the release workflow (see *Building
> releases*): `DiffAnyDoc.exe` on Windows, a `.tar.gz` (with `install.sh`) and
> an AppImage on Linux. From a source checkout, `diffanydoc` is a console script
> inside the virtualenv.

#### OCR (optional)

Scanned PDFs and images need [Tesseract](https://github.com/tesseract-ocr/tesseract)
(Apache-2.0) to compare their *text*; without it they are still compared
visually.

```bash
sudo apt install tesseract-ocr tesseract-ocr-tur      # Debian/Ubuntu
winget install UB-Mannheim.TesseractOCR               # Windows
```

DiffAnyDoc finds `tesseract` on `PATH` (on Windows also in `Program Files`), or
at `DIFFANYDOC_TESSERACT`. It uses the installed English and Turkish data by
default (`--ocr-lang` to change). Results are cached per file content in
`~/.cache/diffanydoc/ocr` (`%LOCALAPPDATA%\DiffAnyDoc\cache` on Windows;
`DIFFANYDOC_CACHE_DIR` to move it).

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
- **Check for Updates** — asks GitHub for the latest release when you press
  *Check now* (never automatically; no identifiers are sent) and links to the
  download page

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
diffanydoc diff a.xlsx b.xlsx                     # per-cell changes: "C4: 5200 → 5300"
diffanydoc diff a.docx b.docx --formatting        # also bold/heading/style changes
diffanydoc diff scan-a.pdf scan-b.pdf --ocr-lang tur+eng
diffanydoc diff a.pdf b.pdf --visual on           # pixel comparison of every page
diffanydoc diff a.txt b.txt --format json         # machine-readable output
diffanydoc diff a.pdf b.pdf --fail-on-diff        # exit code 1 when different
diffanydoc info document.docx                     # sections, tables, warnings
diffanydoc formats                                # formats + OCR availability
diffanydoc check-update
diffanydoc select left a.pdf                      # hand a file to the running window
```

| Option | Default | Meaning |
|---|---|---|
| `--no-reflow` | reflow on | compare PDF lines as printed instead of re-joined paragraphs |
| `--formatting` | off | report rows whose text is equal but formatting changed |
| `--visual auto\|on\|off` | auto | pixel comparison; *auto* runs it for images and scanned pages |
| `--ocr auto\|off\|force` | auto | OCR pages without a text layer / never / every page |
| `--ignore-case`, `--exact-whitespace` | | normalisation |
| `--context N`, `--full` | 3 | unchanged lines kept around changes / no folding |

`--fail-on-diff` is designed for CI; with `--visual on` a visual change also
counts:

```bash
git config diff.diffanydoc.command 'diffanydoc diff --fail-on-diff $2 $5'
```

### What the comparison does with each format

- **Byte check first.** Identical files (sha256) are reported as such without
  parsing.
- **PDF.** Words with coordinates → visual lines → paragraphs (a line is joined
  to the next one only when it *wrapped*: the next line's first word would not
  have fitted). Hyphenated line ends are re-joined. Pages are aligned first, so
  an inserted page is one inserted page.
- **Word.** The text as it reads with all tracked changes accepted; the file's
  pending revisions are listed in the result. Clause numbers are computed from
  `numbering.xml` and shown next to the paragraph, but kept out of the compared
  text — inserting clause 3 does not mark clauses 4…20 as changed.
- **Tables (Word, Excel, CSV).** Rows are aligned first; inside a changed row,
  cells are aligned by content, so an inserted column is one inserted cell.
- **Scans.** OCR text is compared like any other text (with a warning that
  recognition errors are possible), and the visual diff runs automatically.
- **Visual diff.** Pages are rendered (100 dpi), the shift between them is
  estimated from ink profiles and corrected, both are softened equally, and
  only ink that has no counterpart nearby counts. Edge residue from blur, JPEG
  noise or sub-pixel shifts is filtered out per region.

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
    model.py          # Document / Page / Block / Span + DiffResult / Row / CellDiff
    normalize.py      # NFKC, typography, soft hyphen, whitespace normalisation
    layout.py         # hyphen joining, paragraph reflow (geometry aware)
    adapters/         # base.py (registry), pdf, docx, xlsx, image, text (+csv)
    diff/             # align.py (pages), lines.py (lines, cells, formatting),
                      # engine.py, geometry.py (page boxes)
    render.py         # page rasterisation (pdfium / Pillow), cached
    visual.py         # registration + pixel diff + regions + overlay
    ocr.py            # Tesseract engine, TSV parsing, disk cache
    report/           # html.py, json.py
  cli.py              # reference consumer of every feature
  updates.py          # GitHub release check (user-triggered)
  web/                # FastAPI + build-free SPA
  desktop/            # pywebview shell (local API + native window)
packaging/            # PyInstaller spec, frozen entry point, Linux desktop entry
tools/build.py        # build + smoke test + archive (+ AppImage)
```

The engine under `core/` knows nothing about Qt or HTTP, so the CLI, API and
desktop share the same code and the engine is tested separately.

### Diff layers

| Layer | Status | Note |
|---|---|---|
| Byte (sha256) | **done** | fast path for identical files |
| Structure (docx XML, xlsx cells) | **done** | tables, sections, numbering, tracked changes |
| Text (line/paragraph + word) | **done** | reflow for PDF/OCR |
| Table cells | **done** | row alignment, then cell alignment |
| Formatting | **done** | opt-in (`--formatting`) |
| Page mapping | **done** | exact anchors + similarity alignment; sheets by name |
| Visual (pixel) | **done** | registration, tolerance, regions, overlay |
| OCR layer | **done** | Tesseract when installed, cached |

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
| `openpyxl` | MIT | Excel workbooks |
| Tesseract (separate program, optional) | Apache-2.0 | OCR |
| PyInstaller (build time only) | GPL + bootloader exception | bundles may use any licence |
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
- **M2 — visual diff** ✅ page rendering, registration, tolerant pixel diff,
  regions, overlay view; similarity-based page alignment; image adapter
- **M3 — DOCX/XLSX** ✅ structural adapters, table-cell alignment, formatting changes
- **M4 — OCR** ✅ Tesseract fallback for scans and images + cache
- **M5 — distribution** ✅ PyInstaller bundles, release workflow, update check;
  *open:* code signing, installers (MSI/winget, Flatpak), the licence decision

Next candidates: moved-paragraph detection, PowerPoint/ODF adapters, a
"compare folders" mode, and a DOCX/PDF cross-format page view (render DOCX via
LibreOffice when installed).

## Building releases

```bash
pip install -e ".[web,desktop,build]"
python tools/build.py
# dist/DiffAnyDoc/                       the bundle (DiffAnyDoc + diffanydoc-cli)
# dist/DiffAnyDoc-<version>-<os>-<arch>.zip | .tar.gz
```

`tools/build.py` runs PyInstaller with `packaging/diffanydoc.spec`, smoke-tests
the bundle (version, formats, a real diff of `samples/`) and archives it. The
bundle contains two programs: **DiffAnyDoc** (windowed: no arguments opens the
window, files open a comparison, commands work like the CLI — the context menu
uses it) and **diffanydoc-cli** (console, for terminals and CI). On Linux the
archive includes `install.sh` (per-user install, menu entry, file-manager
integration); an AppImage is built too when `appimagetool` is on `PATH`.

Pushing a tag `v*` runs `.github/workflows/release.yml`, which builds Windows
and Linux bundles and attaches them to a **draft** release; publishing it stays
manual. The in-app update check reads the latest *published* release.

## Tests

```bash
pytest
```

Test fixtures generate PDFs, Word and Excel files at runtime
(`tests/pdfgen.py`, `tests/officegen.py`); no binaries are kept in the test
suite. OCR tests use a fake engine; one test runs the real Tesseract when it is
installed. Files under `samples/` are there for manual testing.

## Known limitations

- OCR quality is Tesseract's: low-resolution or skewed scans produce
  recognition errors, which show up as text changes (the warning says so).
- Paragraph reflow is a layout heuristic: two-column layouts are compared line
  by line (they are never joined wrongly, only not joined).
- Word: fields are compared by their displayed result; embedded objects and
  images are not compared (use a PDF export with `--visual on` for those).
- Excel: formulas without a cached result (files saved by tools that do not
  calculate) are compared by their formula text; charts and pivot tables are
  not compared.
- Legacy binary `.doc`/`.xls` files are not supported; save them as
  `.docx`/`.xlsx`.
- The visual diff marks a re-wrapped paragraph as one changed area — it is the
  text view that says which words changed.
