# DiffAnyDoc — Task Board & Agent Roadmap (`TODO.md`)

> **CRITICAL DESIGN & ARCHITECTURE RULES FOR ALL AI AGENTS**:
> 1. **STRICT GNOME & CINNAMON DESIGN LANGUAGE**: Never deviate from or abandon **GNOME (libadwaita / HIG)** and **Cinnamon** desktop design conventions. Follow clean flat surfaces, header bars, pill-shaped toggles, standard palette tokens (`--window-bg-color`, `--view-bg-color`, `--headerbar-bg-color`), and precise radii. **FORBIDDEN**: Generic web-framework themes, Tailwind gradients, glassmorphism, floating card drop shadows, or loud non-native animations.
> 2. **PERMISSIVE COMMERCIAL LICENSES ONLY**: Every dependency must be MIT, Apache-2.0, or BSD. **Strictly NO GPL, AGPL, or LGPL**.
> 3. **WORK PROTOCOL**:
>    - Select an open task `[ ]` from the list below.
>    - Mark it as `[⏳ IN PROGRESS: <Your Agent Name>]` with timestamp before starting.
>    - Always stay on the `development` branch (never commit to `main`).
>    - Run `.venv/bin/pytest -v` to ensure 100% test pass rate.
>    - When complete, update status to `[x] DONE` with a brief summary, and update `CHANGELOG.md`.

---

## Task Board Summary

| ID | Priority | Area | Title | Status |
| :--- | :--- | :--- | :--- | :--- |
| **TASK-01** | High | UI / UX | Single-Tab Close & Return to Home Screen | `[x] DONE` |
| **TASK-02** | High | Performance | Cold-Start & Startup Latency Optimization | `[x] DONE` |
| **TASK-03** | High | Visual / Engine | Page View Bounding Box Calibration & Custom Color | `[x] DONE` |
| **TASK-04** | Medium | Legal / Docs | Commercial EULA & License Agreement Page | `[x] DONE` |
| **TASK-05** | Medium | UI / Docs | In-App Help & User Guide Modal | `[x] DONE` |
| **TASK-06** | Medium | Web / UI | "Check for Updates" Modal with GitHub Tag Diff | `[x] DONE` |
| **TASK-07** | High | UI / Viewer | Page View & X-Ray Zoom / Magnifier Controls | `[x] DONE` |
| **TASK-08** | High | DevOps / CI | Automated Release Builds (Windows Exe, Installer, Linux, PyPI) | `[x] DONE` |
| **TASK-09** | Medium | Design / Desktop | High-Resolution App Icon & OS Asset Integration | `[x] DONE` |
| **TASK-10** | High | UI / UX | Difference Navigation Controls (Sticky Topbar & Keyboard Shortcuts) | `[x] DONE` |
| **TASK-11** | High | Desktop / UX | Linux Desktop Drag-and-Drop (WebKit2GTK URI / File Drop) Fix | `[ ] OPEN` |
| **TASK-12** | High | Integration / OS | File Manager Context Menu Integration ("Compare with DiffAnyDoc") | `[ ] OPEN` |
| **TASK-13** | High | Engine / UI | Pure-stdlib A4 Page Layout & Sheet View for Office/Text Documents | `[ ] OPEN` |

---

## Detailed Task Specifications

### [TASK-01] Single-Tab Close & Return to Home Screen
- **Status**: `[x] DONE` - `×` on the last tab (once it holds files) and `Ctrl+W` reset to a clean home screen (files, preload hashes, mode, zoom).
- **Priority**: High
- **Files**:
  - `src/diffanydoc/web/static/app.js` (`closeTab`, `updateSessionTabs`, `resetToUpload`)
  - `src/diffanydoc/web/static/index.html` (`#session-tabs`, `.tab-close`)
  - `src/diffanydoc/locales/en.json`, `src/diffanydoc/locales/tr.json`
- **Problem Statement**:
  - Currently, when only a single comparison tab is open, users cannot close it, or closing it leaves an empty, broken view.
- **Requirements**:
  - When only 1 tab exists, show a close button `×` on the tab (or allow closing via shortcut `Ctrl+W` / `Cmd+W`).
  - Closing the last remaining tab must terminate the comparison session and smoothly transition the view back to the clean home upload screen (`#view-upload`).
  - Clear the file inputs, preload cache references, and reset state cleanly so a new comparison can start fresh.

---

### [TASK-02] Cold-Start & Startup Latency Optimization
- **Status**: `[x] DONE` - Window opens at once with a splash; uvicorn starts in parallel and the app URL loads when `/api/health` answers. `diffanydoc.desktop` import 352 ms -> 67 ms (no FastAPI on the GUI path). OCR/PDF libs were already lazy. Also fixed: desktop refused to start on Windows/macOS (`DISPLAY` check).
- **Priority**: High
- **Files**:
  - `src/diffanydoc/desktop/app.py`
  - `src/diffanydoc/web/server.py`
  - `src/diffanydoc/core/ocr.py`
  - `src/diffanydoc/cli.py`
- **Problem Statement**:
  - Launching the desktop app takes several seconds because heavy modules (FastAPI, ONNX runtime, RapidOCR, PIL, PDFPlumber) are imported synchronously before the GUI window appears.
- **Requirements**:
  - **Lazy Imports**: Move heavy third-party imports (`rapidocr_onnxruntime`, `pypdfium2`, `pdfplumber`, `PIL`) inside their respective function calls or background worker threads.
  - **Instant Window Paint**: Ensure the pywebview native window renders a lightweight splash/skeleton UI immediately while the local server and adapters finish initializing in the background.
  - Profile startup with `python -X importtime -m diffanydoc desktop` and aim for `< 800ms` window appearance.

---

### [TASK-03] Page View Bounding Box Calibration & Custom Color
- **Status**: `[x] DONE` - Measured root cause: pages with a CropBox != MediaBox used MediaBox origin and size, so boxes were shifted/scaled. `pdf.py` now crops to the CropBox and shifts all boxes (test: `test_text_boxes_match_render_on_cropped_page`). On plain pages boxes already match the ink. Box outline presets (Amber, Ruby, Accent blue, High contrast) in the page toolbar, saved in `localStorage`.
- **Priority**: High
- **Files**:
  - `src/diffanydoc/core/diff/geometry.py` (`_rect`, `line_rects`, `_visual_lines`)
  - `src/diffanydoc/core/adapters/pdf.py` (`_group_lines`, coordinate translation)
  - `src/diffanydoc/web/static/app.js` (rendering `.page-box` overlay elements)
  - `src/diffanydoc/web/static/app.css` (`.page-box`, `.page-box-word`)
  - `src/diffanydoc/web/static/index.html` (color picker / preset control)
- **Problem Statement**:
  - In Page View, bounding boxes around changed words currently sit slightly higher than the actual text due to baseline vs bounding box top offset differences between `pdfplumber` and `pypdfium2` rendering.
  - Users have no way to customize or change the highlight border color.
- **Requirements**:
  - **Y-Offset Alignment**: Calibrate coordinate scaling and vertical shift so bounding boxes hug the rendered text baseline and cap-height tightly on all DPI settings (`1.0x`, `1.5x`, `2.0x`).
  - **Customizable Box Color**: Add a color selector (or 4 Adwaita color presets: Amber/Orange, Ruby/Red, Accent Blue, High-Contrast Black/Neon) in the visual diff toolbar, saved to `localStorage`.

---

### [TASK-04] Commercial EULA & License Agreement Page
- **Status**: `[x] DONE` - Replaced placeholder GPLv3 with a formal commercial End User License Agreement (EULA) in `LICENSE` and `EULA.md`. Added `THIRD_PARTY_NOTICES.md` documenting all permissive dependencies. Redesigned `#license-dialog` in `index.html` with GNOME HIG tabbed panels ("Commercial Terms", "Privacy & Data", "Third-Party Notices"), styled in `app.css` and wired in `app.js`. Full 1:1 bilingual Turkish/English translations in `locales/`.
- **Priority**: Medium
- **Files**:
  - `src/diffanydoc/web/static/index.html` (modal `#dlg-license`)
  - `src/diffanydoc/web/static/app.js`
  - `src/diffanydoc/locales/en.json`, `src/diffanydoc/locales/tr.json`
  - `LICENSE` / `EULA.md`
- **Problem Statement**:
  - The current license agreement modal is a placeholder. DiffAnyDoc will be sold as a proprietary commercial product and requires legally sound, clear commercial terms.
- **Requirements**:
  - Draft a commercial End User License Agreement (EULA) covering:
    - Proprietary commercial software grant (per-seat / machine license).
    - Permissive open-source third-party attributions (MIT, Apache-2.0, BSD-3 notices).
    - Disclaimer of warranties & limitation of liability.
    - Privacy guarantee: 100% offline, local processing; no document telemetry.
  - Present this cleanly in the modal with a tabbed view: "Commercial Terms" and "Third-Party Notices".

---

### [TASK-05] In-App Help & User Guide Modal
- **Status**: `[x] DONE` - Help dialog with Quick start / Views / Merging / Marks / Shortcuts tabs; menu entry and `F1`. Lists only shortcuts that exist; added `Ctrl+O`. Not added: `F5` swap and `Ctrl+F` find (no such features yet).
- **Priority**: Medium
- **Files**:
  - `src/diffanydoc/web/static/index.html` (modal `#dlg-help`)
  - `src/diffanydoc/web/static/app.js`, `app.css`
  - `src/diffanydoc/locales/en.json`, `src/diffanydoc/locales/tr.json`
- **Problem Statement**:
  - Users and evaluators need quick onboarding to discover non-obvious features (X-Ray Vision, manual box annotations, gutter merge arrows, keyboard shortcuts).
- **Requirements**:
  - Create a structured, tabbed Help dialog:
    - **Quick Start**: Drag-and-drop, speculative loading, selecting files.
    - **Comparison Modes**: Text Diff vs Page View vs X-Ray Pixel Diff.
    - **Merging**: How to use `→` / `←` gutter copy buttons and bulk merge.
    - **Manual Annotations**: Drawing custom bounding boxes with the "Mark on page" tool.
    - **Keyboard Shortcuts Reference**: `Ctrl+O` (Open), `Ctrl+W` (Close Tab), `F5` (Swap Sides), `Ctrl+F` (Find), `Ctrl++` / `Ctrl+-` (Zoom).

---

### [TASK-06] "Check for Updates" Modal with GitHub Tag Diff
- **Status**: `[x] DONE` - Menu item runs `GET /api/updates`; shows current vs latest, release notes (safe Markdown subset, no innerHTML), download button (system browser in desktop), green check when latest, error text on failure. "Check now" retries.
- **Priority**: Medium
- **Files**:
  - `src/diffanydoc/web/static/index.html` (`#dlg-updates`)
  - `src/diffanydoc/web/static/app.js` (`checkUpdates`, dialog UI render)
  - `src/diffanydoc/updates.py`
  - `src/diffanydoc/locales/en.json`, `src/diffanydoc/locales/tr.json`
- **Problem Statement**:
  - Backend update logic (`updates.py` and `/api/updates`) is ready, but the frontend modal only shows static text instead of actively querying `/api/updates` and showing release notes.
- **Requirements**:
  - Connect "Check for Updates" menu button to call `GET /api/updates`.
  - Display current version vs latest remote version tag (e.g., `v0.2.0` vs `v1.0.0`).
  - If a newer version is found, render the Markdown release notes and an "Open Download Page" button linking to GitHub Releases.
  - If already on the latest version, display an Adwaita green checkmark and "You are on the latest version." badge.

---

### [TASK-07] Page View & X-Ray Zoom / Magnifier Controls
- **Status**: `[x] DONE` - Zoom 25-400 %: step buttons, 100 %, Fit width (default), Fit page; `Ctrl`+wheel keeps the point under the cursor; `Ctrl` `+`/`-`/`0`; `Space`+drag or middle-drag pans. Canvas width = page points x zoom, boxes are % so they scale; image DPI follows zoom (120-300).
- **Priority**: High
- **Files**:
  - `src/diffanydoc/web/static/index.html` (`.zoom-toolbar`, zoom buttons, zoom slider)
  - `src/diffanydoc/web/static/app.js` (CSS transform zoom & pan state handler)
  - `src/diffanydoc/web/static/app.css` (`.zoom-container`, `.zoomable`)
  - `src/diffanydoc/locales/en.json`, `src/diffanydoc/locales/tr.json`
- **Problem Statement**:
  - When comparing high-resolution scanned PDFs or tiny fine-print contracts, users cannot zoom in or pan around the pages in Page View or X-Ray View.
- **Requirements**:
  - Add a floating or header zoom control in Page View and X-Ray View:
    - Zoom In (`+`), Zoom Out (`-`), Reset / 100% (`1:1`), Fit Width / Fit Page.
    - Mouse wheel zoom (`Ctrl + Wheel`).
  - Pan support: When zoomed in beyond viewport size, allow drag-to-pan with the hand tool (`space + drag` or middle-click drag).
  - Ensure bounding box overlay coordinates scale synchronously with the zoom factor.

---

### [TASK-08] Automated Release Builds (Windows Exe, Installer, Linux, PyPI)
- **Status**: `[x] DONE` - `tools/build.py` targets per OS: Windows portable zip + Inno Setup installer (`packaging/windows/installer.iss`), Linux tar.gz + AppImage; fails early if `ISCC`/`appimagetool` is missing. `packaging/diffanydoc.spec` is now tracked. `release.yml` adds sdist/wheel and PyPI trusted publishing. Not yet run end to end: first tag build is the real test; the `pypi` environment must be set up on GitHub/PyPI.
- **Priority**: High
- **Files**:
  - `.github/workflows/release.yml`
  - `tools/build.py`
  - `packaging/diffanydoc.spec`
  - `packaging/windows/installer.iss` (Inno Setup script for Windows installer)
- **Problem Statement**:
  - Commercial distribution requires turnkey standalone installers:
    - Windows standalone portable single-executable / folder.
    - Windows `.exe` setup installer with desktop/start menu shortcuts.
    - Linux standalone executable, `.AppImage`, and `.tar.gz`.
    - PyPI package release workflow (`python -m build && twine upload`).
- **Requirements**:
  - In `tools/build.py`, support building both portable `.zip` and Inno Setup installer for Windows.
  - In `.github/workflows/release.yml`, produce:
    1. `DiffAnyDoc-<ver>-windows-x86_64-portable.zip`
    2. `DiffAnyDoc-<ver>-windows-x86_64-installer.exe`
    3. `DiffAnyDoc-<ver>-linux-x86_64.AppImage`
    4. `DiffAnyDoc-<ver>-linux-x86_64.tar.gz`
    5. Python source distribution `.tar.gz` and wheel `.whl`.

---

### [TASK-09] High-Resolution App Icon & OS Asset Integration
- **Status**: `[x] DONE` - Icon set already existed (`tools/make_icon.py`: SVG favicon, 512 px PNG window icon, ICO 16-256 px used by the spec/installer, `.desktop` entry). Fixed `install.sh` to put the 512 px PNG in `hicolor/512x512`. Logo concept unchanged (design decision for the owner).
- **Priority**: Medium
- **Files**:
  - `src/diffanydoc/web/static/icon.png`
  - `packaging/diffanydoc.ico` (multi-res 16, 32, 48, 64, 128, 256 px)
  - `packaging/linux/diffanydoc.desktop`
  - `src/diffanydoc/desktop/app.py` (window icon hook)
- **Problem Statement**:
  - The application currently runs with no custom icon (default OS generic python/window icon).
- **Requirements**:
  - Create a modern, professional vector-styled logo for DiffAnyDoc:
    - Concept: Two overlapping document sheets with an illuminated diff lens / split-view accent (libadwaita palette).
  - Export PNG sizes: 16x16, 24x24, 32x32, 48x48, 64x64, 128x128, 256x256, 512x512.
  - Generate multi-resolution `diffanydoc.ico` for Windows.
  - Embed icon into:
    - `pywebview` window (`webview.create_window(..., icon=...)`).
    - Web tab favicon (`<link rel="icon">`).
    - Linux `.desktop` and `install.sh`.
    - PyInstaller executable resource.

---

### [TASK-10] Difference Navigation Controls (Sticky Topbar & Keyboard Shortcuts)
- **Status**: `[x] DONE` - Added sticky Adwaita linked pill navigation control in `<header class="topbar">` (`#top-diff-nav`) with Previous (`▲`), Next (`▼`), and current/total counter. Synchronized across Text, Pages, and X-Ray views with smooth scrolling and outline highlights. Added full keyboard shortcuts: `F7` / `Shift+F7`, `N` / `P`, `Alt+Down` / `Alt+Up`, and `F3` / `Shift+F3`.
- **Priority**: High
- **Files**:
  - `src/diffanydoc/web/static/index.html` (`#top-diff-nav`, `#help-dialog` shortcuts table)
  - `src/diffanydoc/web/static/app.css` (`.diff-nav`, `.diff-nav-btn`, `.diff-nav-count`, `.row.current`)
  - `src/diffanydoc/web/static/app.js` (`updateChangeNav`, `collectChanges`, `gotoChange`, `keydown` shortcuts)
  - `src/diffanydoc/locales/en.json`, `src/diffanydoc/locales/tr.json` (`nav.next`, `nav.prev` tooltips with shortcut cues)
- **Problem Statement**:
  - Users reading long documents had to scroll back up or hunt manually for changes once the view header scrolled off-screen.
- **Requirements**:
  - Provide persistent, sticky difference navigation directly in the header bar.
  - Display current change index and total changes (e.g. `1 / 14`).
  - Next/Previous change buttons that smoothly scroll to and highlight each change (`.current`).
  - Full keyboard shortcut support (`F7`, `Shift+F7`, `N`, `P`, `Alt+Up`, `Alt+Down`, `F3`).
  - Maintain strict GNOME Adwaita & Cinnamon design aesthetics.

---

### [TASK-11] Linux Desktop Drag-and-Drop (WebKit2GTK / URI Drop) Fix
- **Status**: `[ ] OPEN`
- **Priority**: High
- **Files**:
  - `src/diffanydoc/desktop/app.py` (`resolve_dropped_uris`, GTK DND target signals)
  - `src/diffanydoc/web/static/app.js` (`setupDropZones`, `handleUriDrop`, `hasFiles`)
- **Problem Statement**:
  - Dragging and dropping files from Linux file managers (Nautilus, Nemo, Dolphin) onto the desktop window does not populate the comparison drop zones.
  - In WebKit2GTK on Linux, `dataTransfer.files` is frequently empty due to browser security restrictions on local filesystem paths, and `text/uri-list` or `text/plain` drops must be properly routed and resolved to canonical paths via desktop IPC.
- **Requirements**:
  - Ensure drag-over visual feedback triggers reliably across all Linux desktop environments (GNOME, Cinnamon, XFCE, KDE).
  - Robustly extract URI lists and paths from `dataTransfer` (`text/uri-list`, `text/plain`, `application/x-moz-file`).
  - Connect native GTK drag-and-drop signals in `diffanydoc.desktop.app` when running under WebKit2GTK if webview security drops URIs.
  - Test and verify single-file drop (fills left or right depending on drop zone) and two-file simultaneous drop (fills both A and B).

---

### [TASK-12] File Manager Context Menu Integration ("Compare with DiffAnyDoc")
- **Status**: `[ ] OPEN`
- **Priority**: High
- **Files**:
  - `src/diffanydoc/integrate.py`
  - `src/diffanydoc/cli.py` (`integrate` subcommand)
  - `src/diffanydoc/web/static/index.html` (Desktop integration action / settings menu entry)
  - `src/diffanydoc/locales/en.json`, `src/diffanydoc/locales/tr.json`
- **Problem Statement**:
  - Users want to right-click files in their file manager to directly launch or compare them with DiffAnyDoc.
- **Requirements**:
  - Support Linux file managers:
    - **Nemo (Cinnamon)**: `.nemo_action` entry in `~/.local/share/nemo/actions/`.
    - **Nautilus (GNOME)**: Nautilus scripts in `~/.local/share/nautilus/scripts/` and Desktop Action in `.desktop`.
    - **Dolphin (KDE)**: Service menu `.desktop` in `~/.local/share/kservices5/ServiceMenus/` / `kio/servicemenus`.
  - Support **Windows Explorer**:
    - Context menu commands under `HKCU\Software\Classes\*\shell\DiffAnyDoc` ("Select Left File (A)", "Compare with DiffAnyDoc...").
  - Provide a one-click "Install File Manager Integration" button in the app's menu/dialog in addition to `diffanydoc integrate install`.

---

### [TASK-13] Pure-stdlib A4 Page Layout & Sheet View for Office/Text Documents
- **Status**: `[ ] OPEN`
- **Priority**: High
- **Files**:
  - `src/diffanydoc/core/model.py` (`Page`, `renderable` flags)
  - `src/diffanydoc/core/diff/engine.py` (Pagination generation for `.docx`, `.doc`, `.odt`, `.rtf`, `.xlsx`, `.txt`)
  - `src/diffanydoc/web/static/app.js` (`renderPages`, DOM sheet layout)
  - `src/diffanydoc/web/static/app.css` (`.page-sheet`, A4 styling, typography)
- **Problem Statement**:
  - Currently, office documents (`.docx`, `.doc`, `.odt`, `.rtf`, `.xlsx`) disable the **Pages** and **X-Ray** views because they are not rasterized by `pypdfium2`. Users expect to see these documents formatted as printable A4 page cards alongside PDFs.
- **Requirements**:
  - Implement **Option 1**: A pure-stdlib, zero-external-dependency A4 sheet paginator using the existing `Document -> Page -> Block` IR.
  - Paginate paragraphs, headings, and tables into standard A4 sheets (approx. 595 × 842 pt / 1123 × 794 px at 96 DPI).
  - Enable the **Pages** tab for office formats, rendering interactive A4 card views with highlighted inline word diffs, bounding boxes, and box color switching.
  - Comply 100% with commercial permissive licensing (no LibreOffice/Word runtime requirements).
