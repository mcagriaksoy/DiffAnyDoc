# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.7.0] - 2026-11-15

### Added
- **Local AI Semantic Comparison (`src/diffanydoc/core/ai.py` + `✨ AI` View + Inline Row AI & Report Integration)**:
  - **Phase 1 (Local Engine & `✨ AI` Tab)**: Added a 100% offline Local AI engine powered by Mozilla's `llamafile` (Apache-2.0) and 6 pluggable GGUF presets (`SmolLM2-135M-Instruct` ~105 MB Tiny, `Qwen2.5-0.5B-Instruct Q2_K` ~215 MB Nano, `SmolLM2-360M-Instruct` ~258 MB Featherweight, `Qwen2.5-0.5B-Instruct Q4_K_M` ~398 MB Ultra-Fast, `Qwen3-0.6B Q4_K_M` ~395 MB Next-Gen Fast, `Qwen2.5-1.5B-Instruct` ~986 MB Balanced, or any custom `.gguf`/`.llamafile` model such as `Qwen3.8-Flash-Next` or local OpenAI-compatible server on `127.0.0.1`). Feeds a compact structured JSON digest (`build_comparison_digest`) of content differences and layout shifts to the local model, returning an executive summary, overall semantic verdict (`identical_meaning`, `layout_only`, `minor_changes`, `major_changes`), and numbered semantic findings (`content`, `rewording`, `layout`) with one-click jumps to `Text` and `Pages` views, plus a 1-click background model downloader (`/api/ai/download`).
  - **Phase 2 (Inline Row AI Explanation, HTML/PDF Report Integration & CLI `--ai`)**:
    - Added row-level on-demand AI explanations (`explain_row_with_ai` / `POST /api/compare/{id}/ai/row`) and a **`✨ AI ile Açıkla`** (`Explain with AI`) action button on selected rows in `Text` view, plus inline `.ai-inline-pill` badges displaying AI semantic annotations directly alongside diff rows.
    - Embedded the Local AI Semantic Summary, Verdict, and Numbered Findings into exported **HTML reports** (`src/diffanydoc/core/report/html.py`), **printable PDF reports** (`src/diffanydoc/core/report/pdf.py`), **JSON output** (`src/diffanydoc/core/report/json.py`), and added the `--ai` flag to `diffanydoc diff` in [`src/diffanydoc/cli.py`](file:///home/mcagriaksoy/Desktop/DiffAnyDoc/src/diffanydoc/cli.py).
- **Numbered Layout-Shift Matching (`1, 2, 3...`), Split/Wrapped Line Reconciliation & SVG Arrow Overlays**:
  - Added `_reconcile_split_lines` and exact-move reservation in `engine.py` so text blocks that moved vertically/horizontally, changed reading order, or wrapped across different column widths are paired 1:1 instead of being painted as deletions, insertions, or modified text.
  - Sequentially numbers every shifted/reordered block (`#1`, `#2`, `#3`...) across both `Text` and `Pages` views:
    - **`Pages` & `X-Ray` Views**: Draws numbered `.rect-shift-badge` callouts (`1`, `2`, `3`) on Left and Right pages, on-page SVG displacement vector arrows (`page-shift-svg`) from ghost origin boxes to new locations, and cross-page cubic Bezier arrows (`cross-page-svg`) connecting `#1` on Left Page A to `#1` on Right Page B.
    - **`Text` View**: Styles pure position shifts with `.row.shifted` (accent-blue indicator rather than red/green/amber error colors) and displays `#1 · Sağda mevcut (→ Δx +50pt)` / `#1 · Soldan kaydı (→ Δx +50pt)`.
- **Switchable Full-PDF Visual/Position Mode vs. Ignore Layout Shifts (Text-Only) Mode**: Added coordinate shift detection (`_detect_position_shifts` in `engine.py` and `"shift"` overlay boxes in `geometry.py`) alongside an instant topbar switch (`#opt-text-only-mode`, labeled `"Ignore layout shifts (Text only)"` / `"Kaymaları yok say (Sadece metin)"` with tooltip and Help documentation in `#help-dialog`) backed by `/api/compare/{id}/recompare`.

### Changed
- **Large `.docx` (12 MB+ / 198+ Pages) Backend & UI Responsiveness Optimizations**:
  - **Lazy DOCX Media Loading (`adapters/docx.py`, `render.py`)**: Deferred reading embedded images larger than 256 KB from `.docx` ZIP archives until a page is actually rendered in `Pages` view, eliminating multi-megabyte buffer decompression and `deepcopy` overhead during `load()` and `preload_document()`.
  - **Pagination, Reflow & Alignment Scaling (`layout.py`, `diff/lines.py`, `diff/align.py`, `diff/engine.py`)**: Skipped per-word `Span` generation in synthetic A4 pagination when a document exceeds 600 blocks, restricted `reflow_blocks` strictly to `pdf` and `image` documents, anchored `align_pages` with `SequenceMatcher` and banded Needleman-Wunsch for multi-hundred-page documents, and capped $O(D \times I)$ fuzzy move matching in `_mark_moved_rows` and `_refine_replacement`.
  - **Non-Blocking FastAPI Worker Threadpool & Bounded `llamafile` Threads (`web/server.py`, `core/ai.py`)**: Converted synchronous CPU/IO-bound FastAPI route handlers (`compare`, `preload`, `recompare`, `ai`) from `async def` to `def` so they execute in Starlette's worker threadpool without blocking the main event loop, and bounded `llamafile` CPU threads (`-t`, `-c 2048`) with a compact 12-item AI digest.
  - **Lazy Tab Rendering & Zero-Reflow Change Navigation (`web/static/app.js`)**: Deferred `renderPages()` until the user enters `Pages` or `X-Ray` mode, avoided calling `applyZoom()`, `collectChanges()`, or `renderMinimap()` DOM queries when switching to `✨ AI` or `Folder` tabs, replaced layout-thrashing `.offsetParent` checks with `.style.display !== "none"`, and sampled minimap markers to at most 240 nodes.
- **Commercial EULA, Privacy Policy, Third-Party Notices, Help & README Updates**:
  - Updated [`LICENSE`](file:///home/mcagriaksoy/Desktop/DiffAnyDoc/LICENSE), [`EULA.md`](file:///home/mcagriaksoy/Desktop/DiffAnyDoc/EULA.md), [`PRIVACY.md`](file:///home/mcagriaksoy/Desktop/DiffAnyDoc/PRIVACY.md), [`NOTICE`](file:///home/mcagriaksoy/Desktop/DiffAnyDoc/NOTICE), [`THIRD_PARTY_NOTICES.md`](file:///home/mcagriaksoy/Desktop/DiffAnyDoc/THIRD_PARTY_NOTICES.md), [`THIRD_PARTY_LICENSES.md`](file:///home/mcagriaksoy/Desktop/DiffAnyDoc/THIRD_PARTY_LICENSES.md), [`README.md`](file:///home/mcagriaksoy/Desktop/DiffAnyDoc/README.md), and in-app `#license-dialog` / `#help-dialog` (`en.json`, `tr.json`) for commercial distribution, including full Apache-2.0 attributions for `llamafile`, `Qwen2.5`/`Qwen3`, and `SmolLM2` plus the Local AI advisory disclaimer.
- **Compact Initial Window & `1366x768` Screen Fit**: Reduced default desktop window dimensions (`1160x700`, minimum `860x560`) and compacted initial upload screen spacing (`.upload-view`, `.status`, `.drop`, plus `@media (max-height: 800px)` rules) so the entire welcome/upload screen fits cleanly on `1366x768` displays without vertical clipping or scrolling.
- **Windows 10/11 Startup, Rendering & OCR Performance Optimizations**:
  - Replaced heavy `import rapidocr_onnxruntime` on startup (`/api/ocr/status`) with zero-import `importlib.util.find_spec("rapidocr_onnxruntime")`, deferring ONNX Runtime / OpenCV DLL loading until OCR actually runs.
  - Added `subprocess.CREATE_NO_WINDOW` on Windows for all Tesseract subprocess calls and skipped redundant `tesseract --list-langs` process creation when embedded RapidOCR is active.
  - Cached in-memory `pypdfium2.PdfDocument` instances and paginated office sheets in `render.py`, added `@lru_cache` to `_get_font` with native Windows fonts (`arial.ttf`, `segoeui.ttf`) prioritized on `win32`, and switched localhost PNG encoding (`render_page_png`, `render_xray_page_png`) to `compress_level=1` (~4.5x faster).
  - Optimized visual page registration (`_estimate_shift` in `visual.py`) with a coarse-to-fine grid search (~3.7x fewer full-page pixel comparisons) and bypassed Windows Registry proxy lookups for `127.0.0.1` health checks in `desktop/app.py`.

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
