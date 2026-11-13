# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.6.0] - 2026-11-13

### Added
- **Auto-Open `Pages` Tab for Non-Text / Scanned PDFs & Images**: Comparisons with no extracted text layer, OCR-only pages, or images now open directly on the `Pages` tab instead of an empty `Text` view.

### Fixed
- **X-Ray-Guided `Pages` Box Clustering (`visual.py`)**: Replaced coarse single-pass row/column projections with two-pass XY splitting + `getbbox()` tightening and X-Ray polarity masks (`_polarity_masks`), so `Pages` boxes tightly hug actual changed ink on each side instead of painting large areas or empty opposite-side space.
- **Windows CLI UTF-8 Output & PyInstaller Smoke Test**: Handled `cp1252` `UnicodeEncodeError` in `cli._emit()` and bundled `pdfplumber` in `diffanydoc.spec` so the Windows portable `.exe` build and smoke test succeed cleanly.

## [0.5.0] - 2026-11-12

### Added
- **Show Boxes Toggle (`#opt-boxes`)**: Added a GNOME/Adwaita switch next to the Box color selector in Pages and X-Ray views to hide all diff/visual highlight rectangles on demand.
- **Side-by-Side Row Matching & Selection (`↔ Select in A/B`)**: Clicking a line in Text view highlights matching lines on the opposite side and offers a one-click button (or `Enter` shortcut; `Esc` clears) to select and scroll to the match.
- **Bidirectional `Text` ↔ `Pages` Sync**: Added `↗ Show on page` on selected text rows to jump to the corresponding page box, and clicking a page box jumps back to and selects the corresponding text row.
- **Compare Progress Bar & Cancel**: Added a progress bar below the Compare button with real-time upload tracking, staged status labels, and a `Cancel` button (`xhr.abort()` / `AbortController`).
- **Ignore Headers, Footers & Page Numbers (`ignore_headers_footers`)**: Added an advanced option to filter repeating top/bottom 7% bands and page numbers in multi-page documents.

### Fixed
- **Pages Tab Over-Highlighting & Merged Heading Boxes**: Stopped emitting full-line boxes on unchanged sides of single-side `replace` insertions, clipped merged heading/OCR `Span` boxes proportionally to only the changed word range (`_clip_span_bbox`), improved `pdfplumber` word splitting (`x_tolerance=2`), defaulted pixel-level visual boxes to off for text-layer PDFs, and deduplicated overlapping visual boxes.
- **CI Test Dependencies**: Added `httpx>=0.27` to `dev` dependencies in `pyproject.toml` so `FastAPI` `TestClient` tests run cleanly in CI.

## [0.4.0] - 2026-11-10

### Added
- **Windows x64 Standalone Portable Executable (`DiffAnyDoc-portable.exe`)**: Added a single-file, turnkey portable binary target for 64-bit Windows environments. Bundles all application components, embedded ONNX OCR engine, document parsers, and webview renderer into a self-contained `.exe` (`DiffAnyDoc-<version>-windows-x86_64-portable.exe`) that executes instantly without installation or unzipping, supplementing the existing portable `.zip` and Inno Setup installer.
- **Preferences & Settings Window (`Ctrl+,`)**: Added a dedicated GNOME libadwaita Preferences modal dialog (`#settings-dialog`) accessible from the main menu and via `Ctrl+,`. Groups system integrations and default comparison preferences into clean Adwaita action rows.
- **Smart Single-Line Context Menu Integration**: Replaced multi-item file manager entries with a single dynamic action across Nemo, Nautilus, Dolphin, and Windows Explorer. Right-clicking a file shows "Select as left file to compare"; once selected, subsequent right-clicks dynamically display "Compare to '<filename>'", instantly comparing both files upon click.
- **Collapsible Advanced Comparison Options**: Cleaned up the upload view by moving options (ignore whitespace, ignore case, compare formatting, numeric tolerance) into an elegant Adwaita disclosure pill ("Advanced comparison options"), keeping the default screen minimal and focused.

### Fixed
- **Sticky Diff Navigation & Header Retention During Scrolling**: Resolved an issue where navigating through differences using "Next change" caused the headerbar, comparison toolbar (`.result-head`), and diff navigation buttons to scroll out of view when jumping to lower rows and pages. Fixed CSS sticky positioning by converting `html, body { height: 100% }` to `min-height: 100%` so containing blocks expand with document height. Introduced a pinned `.result-sticky-header` container sticking right below `.topbar` at `top: 48px`, keeping file names, action buttons (New comparison, Reload, Copy/Merge menu), and Change Navigation controls (`◄ current / total ►`) permanently accessible without requiring manual scrolling back to the top. Added `scroll-padding-top` and `scroll-margin-top: 104px` to guarantee centered difference targets are never obscured by sticky headers.
- **Table Difference Highlighting & Cell-Level Bounding Boxes**: Resolved an issue where modifying a single cell in a table or spreadsheet caused the entire table (all 20+ rows) to be covered by yellow/amber replacement rectangles. Added precise per-row geometry (`row.bbox`) and per-cell span coordinate mapping (`row.spans`) in `paginate_document` and `document_lines`. Replaced legacy full-table line bounding boxes in `server.py` with `change_rects`, and prioritized word/cell-level diff rectangles in `app.js` (`activeRects`) so that unchanged rows remain clean and only the exact changed cells (e.g. "AL" vs "BAL") are highlighted.
- **X-Ray Modal Sizing & Loading Indicator Visibility**: Restructured X-Ray zoom calculation and CSS layout so overlaid comparison pages open at a comfortable, readable size (matching side-by-side page dimensions) rather than blowing up to 100% of widescreen displays. Repositioned the loading spinner and label (`.canvas-spinner`) to the top-visible region of the viewport (`top: min(40%, 180px)`) so users immediately see the loading state while the composite image is being generated. Added `eager` loading on initial display and server-side in-memory caching for `render_xray_page_png` to make subsequent views instant.
- **DOCX Image Extraction & Sheet Rendering**: Enabled OOXML drawing and picture extraction (`<w:drawing>`, `<w:pict>`, `<a:blip>`, `<wp:extent>`) from `.docx` archives and their relationship parts (`word/_rels/document.xml.rels`). Embedded images are now parsed into intermediate representation blocks, paginated in A4 sheet layout, and rendered directly onto comparison page canvases (`render_sheet_page`), making images visible in Pages and X-Ray views and represented as `[Image: <filename>]` in Text comparison mode.
- **JPEG vs PNG False Difference Suppression**: Normalized raster image base resolution to 96.0 DPI across `ImageAdapter` and `render_page`, preventing arbitrary camera/editor EXIF/JFIF DPI metadata (e.g. 72 vs 96 DPI) from causing artificial Lanczos resampling distortion. Increased noise tolerance and introduced region filtering for lossy formats (JPEG, WebP) in `visual.py`, eliminating false positive differences caused by 8x8 DCT ringing artifacts and chroma subsampling jitter while preserving 100% sensitivity to real content changes.
- **Compare Button Initialization in WebKit2GTK**: Resolved an issue where clicking the "Compare" button did not trigger comparison due to unguarded `localStorage` access throwing security exceptions in sandboxed WebKit2GTK / Linux environments, halting event listener registration. Wrapped all client storage calls with defensive error handling and bound primary action controls prior to modal dialog initialization.

## [0.3.0] - 2026-11-08

### Added
- **Folder & Directory Tree Comparison Mode (TASK-19)**: Added recursive directory comparison engine (`diffanydoc.core.folder`) featuring fast SHA-256 matching for 0 ms identification of byte-identical files, modification detection, and tracking of added and removed files. Added `/api/compare-directories` API endpoint, CLI recursive diff (`diffanydoc diff dirA dirB`), and interactive UI Folder View with status badges, size comparisons, quick filters (All, Modified, Added, Removed, Identical), and double-click or "Compare file" action opening individual file diffs directly in new session tabs.
- **Comparative Reading & Vocabulary Analysis Metrics (TASK-18)**: Expanded diff statistics with word counts (Left vs Right), character counts, estimated reading time (~200 words/min), words added/removed, and overall content change density. Added interactive click action on the topbar stats pill opening an Adwaita modal dialog (`#stats-detail-dialog`) showing side-by-side comparative metrics and change breakdown cards.
- **Numeric Tolerance Comparison for Tables & Spreadsheets (TASK-17)**: Added `numeric_tolerance` option to `DiffOptions` (`--tolerance` in CLI, numeric input in Web UI, and API support). Evaluates numeric differences in table cells and text tokens (including currency symbols, percentages, and commas) and treats values differing by at most the tolerance threshold as equal, eliminating false positive modification alerts caused by negligible rounding or floating-point precision jitter.
- **Official PDF & Printable Comparison Report Generator (TASK-16)**: Built an enterprise-grade, multi-page printable PDF comparison report generator (`diffanydoc.core.report.pdf`) using pure-stdlib and Pillow (MIT-CMU, zero AGPL/copyleft dependencies). Includes an executive cover summary (timestamp, Document A vs B metadata, SHA-256 tamper-evident fingerprints, similarity %, additions, deletions, modifications), paginated side-by-side comparison tables with color-coded diff rows and running headers/footers, `/api/compare/{id}/report.pdf` web endpoint, and CLI support (`--format pdf`, `-o report.pdf`).
- **Synchronized In-Document Search & Kind Filters (TASK-15)**: Added synchronized in-document search bar toggled by `Ctrl`+`F` / `Cmd`+`F` or topbar search button. Highlights matching occurrences simultaneously across both document panes with match navigation (`Enter` / `Shift`+`Enter`, next/prev buttons) and match count badge. Added instant kind filter chips ("All", "+Added", "−Removed", "~Changed") with dynamic minimap and diff navigation updating.
- **Vertical Diff Minimap & Overview Gutter (TASK-14)**: Added a subtle GNOME Adwaita overview minimap strip on the right window edge. Visualizes added, deleted, and modified lines/regions proportionally, displays an active scroll viewport indicator, and supports click-or-drag smooth navigation to any change position.
- **A4 Sheet Layout & Page View for Office/Text Documents (TASK-13)**: Implemented pure-stdlib, zero-external-dependency A4 sheet pagination (`paginate_document`) and clean A4 rasterization (`render_sheet_page`) using Pillow. All supported formats (`.docx`, `.doc`, `.odt`, `.rtf`, `.xlsx`, `.txt`) can now be viewed as printable A4 page cards in the Pages and X-Ray views, with per-word bounding box highlights, custom box colors, and zoom support.
- **File Manager Context Menu & Direct Compare (TASK-12)**: Added "Compare with DiffAnyDoc" right-click action for Cinnamon (Nemo `.nemo_action`), GNOME (Nautilus scripts), KDE (Dolphin service menus), and Windows Explorer (`HKCU\Software\Classes\*\shell\DiffAnyDoc.Compare`), launching comparisons directly for selected files. Added in-app one-click Install/Uninstall File Manager Integration menu option in the main menu and local API.
- **Linux Desktop Drag-and-Drop Fix (TASK-11)**: Resolved Linux file manager drag-and-drop issues (Nautilus, Nemo, Dolphin) under WebKit2GTK by prioritizing OS URI list and local path resolution over browser file blobs. Added robust Nautilus clipboard header stripping and URL decoding in `resolve_dropped_uris`. Enabled mixed-source comparisons (local filesystem path + browser upload) in `/api/compare`.
- **Box Color Label & Canvas Loading Indicator**: Added visible "Box color" label text to the color picker menu button in the header bar. Added smooth GNOME Adwaita spinner and loading indicator to Page and X-Ray canvas cards while rasterized/composite page images are being rendered and loaded from the server.
- **Sticky Difference Navigation Controls**: Added GNOME Adwaita linked pill navigation controls in the top header (`#top-diff-nav`) with Previous change (`▲`), Next change (`▼`), and position counter (`current / total`), accessible at all times while scrolling. Supported shortcuts include `F7` / `Shift+F7`, `N` / `P`, `Alt+Up` / `Alt+Down`, and `F3` / `Shift+F3`.
- **Page zoom and pan (TASK-07)**: Fit width, Fit page, 100 % and step zoom (25–400 %) in Pages and X-Ray; `Ctrl` + wheel, `Ctrl` `+` / `-` / `0`; `Space` + drag or middle-drag pans. Page images re-render at a DPI that follows the zoom.
- **Box color presets (TASK-03)**: Amber, Ruby, Accent blue and High contrast outlines for change boxes, saved per browser.
- **Help dialog (TASK-05)**: Quick start, views, merging, marks and a shortcut table; opens from the menu or with `F1`. New `Ctrl+O` opens the file picker.
- **Check for Updates dialog (TASK-06)**: queries `/api/updates`, shows current vs latest version, release notes and a download link, or a green "latest version" state.
- **Close the last tab (TASK-01)**: `×` and `Ctrl+W` return to a clean home screen.
- **Release builds (TASK-08)**: Windows portable `.zip` + Inno Setup installer, Linux `.tar.gz` + AppImage, sdist/wheel and PyPI trusted publishing. The PyInstaller spec is now tracked.
- **Commercial EULA & License Agreement Dialog (TASK-04)**: Replaced placeholder GPL text with a formal proprietary commercial End User License Agreement (`LICENSE`, `EULA.md`) and third-party open-source attributions (`THIRD_PARTY_NOTICES.md`). Upgraded `#license-dialog` to an Adwaita tabbed interface with Commercial Terms, 100% Offline Privacy Guarantee, and Permissive Third-Party Notices tabs.

### Changed
- **Faster desktop start (TASK-02)**: the window opens at once with a splash while the local server starts in parallel; FastAPI is no longer imported on the GUI path.

### Fixed
- Change boxes were shifted on PDF pages whose CropBox differs from the MediaBox; text coordinates and page size now use the CropBox that is rendered.
- `diffanydoc desktop` refused to start on Windows and macOS (it required `DISPLAY`).
- Linux installer put the 512 px icon in the `256x256` icon folder.
- Files dropped from Windows Explorer into the desktop window were ignored (`file:///C:/…` URIs were not resolved).
- CI: `pip install` failed on Python 3.13 because `rapidocr-onnxruntime` supports Python < 3.13 only; `requires-python` and the test matrix now say so.

## [0.2.0] - 2026-11-03

### Added
- **Embedded RapidOCR Engine (Apache-2.0)**: Replaced system-level `tesseract-ocr` dependency with bundled `rapidocr-onnxruntime`. Zero installation required, commercially safe, and fully automatic.
- **Speculative Preloading**: Background parsing and OCR starts the moment File A is selected, eliminating latency while choosing File B.
- **SHA-256 Fast-Check**: Byte-identical files short-circuit parsing and OCR immediately with a 0 ms diff.
- **X-Ray Visual Diff View**: Composite overlay mode for scanned PDFs and images highlighting removed ink (red), added ink (green), and scanner shift compensation.
- **Interactive Manual Annotations**: Added "Mark on page" tool enabling users to draw bounding boxes and add custom notes directly on visual diff pages.
- **Multi-Tab Sessions**: Work on multiple comparisons in parallel with session tabs (open, switch, close).
- **Side-to-Side Merging**:
  - Gutter line-by-line copy buttons (`→` A to B, `←` B to A).
  - Bulk merge controls (`A → B`, `B → A`).
  - Dynamic similarity recalculation and merged document download/export.
- **AI Agent Guidelines**: Added `AGENTS.md` and `CLAUDE.md` defining strict commercial licensing boundaries (permissive only) and architecture roadmap for future AI agents.
- **Packaging & CI/CD (Milestone M5)**:
  - Added PyInstaller desktop bundle build tool (`tools/build.py`) with Linux (`install.sh`, `.desktop`, AppImage) and Windows (`.zip`, `.exe`) support.
  - Added GitHub Actions workflows for continuous integration (`ci.yml`) and automated release bundling (`release.yml`).
- **Paragraph Reflow & Page Alignment**:
  - Added paragraph reflow (`core/layout.py`) to prevent line wrapping shifts in PDF and OCR text from falsifying diff lines.
  - Upgraded page alignment (`core/diff/align.py`) with global Needleman-Wunsch algorithm for robust multi-page pairing.
  - Added word-level and line-level page coordinate bounding boxes mapping (`core/diff/geometry.py`).
- **Privacy-Friendly Update Checks**:
  - Added GitHub release checking module (`diffanydoc.updates`), CLI `check-update` command, and `/api/updates` endpoint.

### Changed
- Removed manual "Enable OCR" UI checkbox in favor of automatic detection on image-based pages.
- UI styling refined according to GNOME HIG / libadwaita design standards.
- Synchronized English (`en.json`) and Turkish (`tr.json`) localization strings with 1:1 key parity.

---

## [0.1.0] - 2026-10-15

### Added
- Initial release: Unified IR side-by-side diff engine supporting PDF, DOCX, XLSX, CSV/TSV, and plain text.
- Desktop GUI powered by pywebview and local FastAPI backend.
- Inline word-level diffing and collapsible unchanged row sections.
- Bilingual localization support (English & Turkish).
