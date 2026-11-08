# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
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
