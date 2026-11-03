# DiffAnyDoc — AI Agent Guide (`AGENTS.md` / `CLAUDE.md`)

> **Read this file before modifying any code.** This document governs all AI coding agents (Claude Code, OpenCode, Cursor, Antigravity, Copilot, etc.) working on **DiffAnyDoc**.

---

## 1. Product Vision & Positioning

**DiffAnyDoc** is a commercial-grade, privacy-first, local-only document & file comparison tool — inspired by **Beyond Compare**, **Kaleidoscope**, and **DeltaWalker**, but built specifically to go **beyond plain text** into rich office, scanned, and visual documents with unique capabilities:

1. **Cross-Format Semantic Comparison**: Compare any combination of `.pdf`, `.docx`, `.doc`, `.odt`, `.rtf`, `.xlsx`, `.xlsm`, `.csv`, `.tsv`, images (`.png`, `.jpg`, `.tiff`, `.webp`, `.bmp`), and source/plain text through a single unified Intermediate Representation (`Document -> Page -> Block`).
2. **X-Ray Vision & Visual Overlay**: Pixel-registered composite diffing (`render_xray_page_png`) that overlays scanned pages or images, compensating for scanner shift (`±4 pt`) and highlighting removed ink in red, added ink in green, and bounding boxes around changed regions — plus **interactive user-drawn bounding box annotations** (`Mark on page`) with custom labels.
3. **Zero-Config Embedded OCR**: Powered by **RapidOCR (`rapidocr-onnxruntime`, Apache-2.0)**. Users never configure OCR checkboxes; pages lacking a text layer or containing scanned images are automatically OCR'd and cached by SHA-256 content hash.
4. **Instant Pre-Loading & Fast Checksum**:
   - **SHA-256 Fast-Check**: Byte-identical files short-circuit before any parser or OCR engine is invoked (`0 ms` comparison).
   - **Speculative Preload (`/api/preload`, `/api/preload-path`, `preload_document`)**: As soon as the user selects the first file (Left / A), parsing and OCR start immediately in the background while the user is still choosing the second file (Right / B).
5. **Interactive Side-to-Side Merging & Multi-Tab Sessions**:
   - In-app session tabs (`#session-tabs`) to hold multiple comparisons simultaneously.
   - Per-line gutter merge arrows (`→` copy line to Right B, `←` copy line to Left A) and bulk merge (`A → B`, `B → A`) with live similarity recalculation and merged document download.

---

## 2. Strict Commercial Licensing Rules (CRITICAL)

**DiffAnyDoc will be sold commercially as a proprietary / closed-source product.**

### NEVER add or link dependencies with copyleft licenses:
- **FORBIDDEN**: `GPL`, `AGPL`, `LGPL` (when statically bundled), `CC-BY-NC`, `SSPL`, or any non-commercial license.
- **SPECIFICALLY FORBIDDEN PACKAGES**:
  - `PyMuPDF` / `fitz` (AGPL-3.0) — **DO NOT USE**
  - `PyQt5` / `PyQt6` (GPL-3.0) — **DO NOT USE**
  - `ghostscript` (AGPL-3.0) — **DO NOT USE**
  - `paddleocr` if pulling GPL sub-packages — **USE `rapidocr-onnxruntime` (Apache-2.0) instead**
  - `unoconv` / `pypandoc` GPL wrappers

### APPROVED Permissive Licenses ONLY:
Every runtime dependency in `pyproject.toml` MUST use **MIT**, **Apache-2.0**, **BSD-2-Clause**, **BSD-3-Clause**, **ISC**, or **Python Software Foundation License**:
- `pdfplumber` (MIT) — PDF text & table structure extraction
- `pypdfium2` (Apache-2.0 / BSD-3) — Fast PDF page rendering
- `Pillow` (MIT-CMU) — Image processing & pixel diffing
- `rapidocr-onnxruntime` (Apache-2.0) — Embedded ONNX OCR engine
- `fastapi` / `starlette` / `uvicorn` (MIT / BSD-3) — Local API server
- `pywebview` (BSD-3) — Native desktop window wrapper (uses OS-provided WebKit2GTK / Edge WebView2 / Cocoa WebKit)

---

## 3. Git Branching & Workflow Rules

1. **Always work on the `development` branch.**
2. **NEVER commit or push directly to `main`.** The `main` branch is reserved strictly for tagged production releases merged by the repository owner.
3. Run the full test suite before finishing any task:
   ```bash
   .venv/bin/pytest -v
   ```
4. Never commit binary test fixtures (`.pdf`, `.docx`, `.xlsx`, `.png`) into the repo. Generate all test documents dynamically at test time using `tests/pdfgen.py`, `tests/docxgen.py`, and `tests/xlsxgen.py`.

---

## 4. Architecture & Codebase Map

```text
src/diffanydoc/
├── core/
│   ├── model.py          # Shared IR: Document, Page, Block, Line, Row, DiffResult, Stats
│   ├── normalize.py      # Unicode NFKC, smart quotes, dash & whitespace normalization
│   ├── ocr.py            # Embedded RapidOCR (Apache-2.0) + optional Tesseract fallback + SHA-256 disk cache
│   ├── render.py         # Thread-safe pypdfium2 & Pillow page rasterization
│   ├── visual.py         # Pixel registration, region detection, and X-Ray composite rendering
│   ├── adapters/
│   │   ├── base.py       # Adapter protocol & extension registry
│   │   ├── pdf.py        # pdfplumber text + ruled table cell extraction
│   │   ├── docx.py       # Pure-stdlib OOXML parser (headers, body, tables, footnotes, run styles)
│   │   ├── doc.py        # Legacy .doc (OLE2 FIB/PieceTable), .odt, and .rtf parser (pure stdlib)
│   │   ├── xlsx.py       # Pure-stdlib OOXML spreadsheet parser + <mergeCells> expansion
│   │   ├── image.py      # Direct image adapter (.png, .jpg, .tiff, .bmp, .webp)
│   │   └── text.py       # Plain text, source code, and CSV/TSV cell-aware parser
│   ├── diff/
│   │   ├── align.py      # Fast line-token page alignment (LCS + greedy leftover pairing)
│   │   ├── lines.py      # Word-level inline diff, punctuation sub-token diff, table cell_diff, style_summary
│   │   └── engine.py     # SHA-256 fast-check, speculative preload cache, row building, auto-folding
│   └── report/
│       ├── html.py       # Self-contained offline HTML diff report
│       └── json.py       # Stable JSON serialization schema
├── web/
│   ├── server.py         # FastAPI endpoints (/api/compare, /api/preload, /api/compare/{id}/xray, etc.)
│   └── static/           # Zero-build vanilla JS/CSS SPA (index.html, app.js, app.css)
├── desktop/
│   └── app.py            # pywebview native window, file picker, URI drop resolver, single-instance IPC
├── locales/
│   ├── en.json           # English strings (must match keys in tr.json 1:1)
│   └── tr.json           # Turkish strings (must match keys in en.json 1:1)
└── cli.py                # CLI entry point (diff, info, formats, serve, desktop, select, integrate)
```

### Golden Architectural Rules:
- **Never convert File A into File B's format.** Every format is parsed into `Document` IR by its adapter in `src/diffanydoc/core/adapters/`.
- **`core/` must never import `fastapi`, `webview`, or UI modules.**
- **Performance matters on large files:**
  - Never run character-level `SequenceMatcher` on concatenated multi-thousand-line strings (causes $O(N^2)$ freezes on large CSV/XLSX files). Always align by normalized line tokens first.
  - Auto-fold unchanged runs above `_AUTO_FOLD_LINE_THRESHOLD` (`1200` lines) so the DOM stays responsive.
- **Internationalization (`i18n`):**
  - Every user-visible string in `index.html`, `app.js`, `html.py`, or `cli.py` must live in both `src/diffanydoc/locales/en.json` and `src/diffanydoc/locales/tr.json`.
  - `tests/test_i18n.py` enforces exact key parity and placeholder parity (`{name}`, `{n}`) between `en.json` and `tr.json`.

---

## 5. UI & Design System Rules (`docs/DESIGN.md`)

Read [`docs/DESIGN.md`](docs/DESIGN.md) before touching `index.html` or `app.css`.
- **STRICT MANDATE: NEVER DEVIATE FROM GNOME & CINNAMON DESIGN ELEMENTS.**
  - DiffAnyDoc is built to look and feel like a first-class citizen on GNOME and Cinnamon desktop environments.
  - Follows **GNOME HIG / libadwaita** and **Cinnamon** desktop conventions: clean header bars, flat content views, Adwaita colour tokens (`--window-bg-color`, `--view-bg-color`, `--headerbar-bg-color`, `--accent-bg-color`), pill switches, and native typography (`Cantarell` / `Ubuntu` / `system-ui`).
  - **ABSOLUTELY FORBIDDEN**: Material Design, Bootstrap, Tailwind gradients, glassmorphism, loud hover animations, non-system shadows, or trendy web gimmicks.
- **Modified rows (`.row.mod .cell`)** must keep a subtle background (`4%` tint + `2px` left warning border) so that **only the inline changed words (`.seg-del`, `.seg-ins`)** stand out clearly — never paint an entire modified paragraph bright yellow/red.
- No external CSS or JS frameworks. Zero-build vanilla JS/CSS.

---

## 6. Active Task Board & Roadmap (`TODO.md`)

All open tasks, priority items, and backlog specifications are actively tracked in **[`TODO.md`](TODO.md)**.
When an AI agent starts working on DiffAnyDoc:
1. Open [`TODO.md`](TODO.md).
2. Mark the selected task as `[⏳ IN PROGRESS: <AgentName>]`.
3. Complete the task following all constraints in this document.
4. Mark the task as `[x] DONE` and update `CHANGELOG.md`.
