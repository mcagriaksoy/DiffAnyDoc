# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

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
