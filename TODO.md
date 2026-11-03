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
| **TASK-01** | High | UI / UX | Single-Tab Close & Return to Home Screen | `[ ] OPEN` |
| **TASK-02** | High | Performance | Cold-Start & Startup Latency Optimization | `[ ] OPEN` |
| **TASK-03** | High | Visual / Engine | Page View Bounding Box Calibration & Custom Color | `[ ] OPEN` |
| **TASK-04** | Medium | Legal / Docs | Commercial EULA & License Agreement Page | `[ ] OPEN` |
| **TASK-05** | Medium | UI / Docs | In-App Help & User Guide Modal | `[ ] OPEN` |
| **TASK-06** | Medium | Web / UI | "Check for Updates" Modal with GitHub Tag Diff | `[ ] OPEN` |
| **TASK-07** | High | UI / Viewer | Page View & X-Ray Zoom / Magnifier Controls | `[ ] OPEN` |
| **TASK-08** | High | DevOps / CI | Automated Release Builds (Windows Exe, Installer, Linux, PyPI) | `[ ] OPEN` |
| **TASK-09** | Medium | Design / Desktop | High-Resolution App Icon & OS Asset Integration | `[ ] OPEN` |

---

## Detailed Task Specifications

### [TASK-01] Single-Tab Close & Return to Home Screen
- **Status**: `[ ] OPEN`
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
- **Status**: `[ ] OPEN`
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
- **Status**: `[ ] OPEN`
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
- **Status**: `[ ] OPEN`
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
- **Status**: `[ ] OPEN`
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
- **Status**: `[ ] OPEN`
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
- **Status**: `[ ] OPEN`
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
- **Status**: `[ ] OPEN`
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
- **Status**: `[ ] OPEN`
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
