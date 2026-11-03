"""Command line interface.

The CLI is the reference consumer of the engine: if a feature works here, it
works everywhere (API, desktop shell, git driver).

Help text is English (developer facing); messages, the text output and reports
follow ``--lang`` / ``DIFFANYDOC_LANG`` and default to English.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .core.adapters import AdapterError, LoadOptions, adapters, load, supported_extensions
from .core.diff import DiffOptions, compare, supported_formats
from .core.report.html import render_html, write_html_report
from .core.report.json import result_to_dict
from .i18n import available_languages, resolve_language, t, warning_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffanydoc",
        description="Compare documents side by side: PDF, DOCX, XLSX, text.",
    )
    parser.add_argument("--version", action="version", version=f"DiffAnyDoc {__version__}")
    parser.add_argument(
        "--lang",
        metavar="CODE",
        choices=available_languages(),
        help="language for messages and reports (default: English)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    diff = subparsers.add_parser("diff", help="compare two files")
    diff.add_argument("left", type=Path, help="left file (A)")
    diff.add_argument("right", type=Path, help="right file (B)")
    diff.add_argument("-o", "--output", type=Path, help="write the report to this file")
    diff.add_argument(
        "--format",
        choices=("html", "json", "text"),
        help="output format (default: from the -o suffix, otherwise text)",
    )
    diff.add_argument(
        "--context", type=int, default=3, help="unchanged lines kept around a change (3)"
    )
    diff.add_argument(
        "--ignore-case", action="store_true", help="treat letter case as equal"
    )
    diff.add_argument(
        "--full", action="store_true", help="do not fold unchanged lines"
    )
    diff.add_argument(
        "--fail-on-diff",
        action="store_true",
        help="exit with code 1 when differences exist (CI / git hooks)",
    )
    diff.add_argument(
        "--exact-whitespace",
        dest="collapse_whitespace",
        action="store_false",
        default=True,
        help="treat differences in spacing as changes",
    )
    diff.add_argument(
        "--no-reflow",
        dest="reflow",
        action="store_false",
        help="compare PDF lines as laid out instead of joining paragraphs",
    )
    diff.add_argument(
        "--formatting",
        action="store_true",
        help="also report formatting-only changes (bold, headings, font size)",
    )
    diff.add_argument(
        "--visual",
        choices=("auto", "on", "off"),
        default="auto",
        help="pixel comparison of rendered pages (auto: for images and scans)",
    )
    diff.add_argument(
        "--visual-dpi", type=int, default=100, help="resolution for the visual comparison"
    )
    diff.add_argument(
        "--ocr",
        choices=("auto", "off", "force"),
        default="auto",
        help="OCR pages without a text layer (auto), never (off) or always (force)",
    )
    diff.add_argument(
        "--ocr-lang",
        metavar="LANGS",
        help="Tesseract languages, e.g. eng+tur (default: installed eng/tur)",
    )

    info = subparsers.add_parser("info", help="show the parsed outline of a file")
    info.add_argument("file", type=Path)
    info.add_argument("--ocr", choices=("auto", "off", "force"), default="auto")
    info.add_argument("--ocr-lang", metavar="LANGS")

    subparsers.add_parser("check-update", help="look for a newer release on GitHub")

    subparsers.add_parser("formats", help="list supported formats")

    serve = subparsers.add_parser("serve", help="start the web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--reload", action="store_true")

    desktop = subparsers.add_parser(
        "desktop", help="open the native desktop window (pywebview)"
    )
    desktop.add_argument("files", nargs="*", type=Path, help="1-2 files to open on start")
    desktop.add_argument("--width", type=int, default=1280)
    desktop.add_argument("--height", type=int, default=860)
    desktop.add_argument("--debug", action="store_true", help="webview developer tools")

    select = subparsers.add_parser(
        "select", help="hand a file to the running window (file-manager integration)"
    )
    select.add_argument("slot", choices=("left", "right"))
    select.add_argument("path", type=Path, help="file to use as the left or right side")

    integrate = subparsers.add_parser(
        "integrate", help="install or remove file-manager context menu entries"
    )
    integrate.add_argument("action", choices=("install", "uninstall"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    language = resolve_language(args.lang)
    try:
        if args.command == "diff":
            return _diff(args, language)
        if args.command == "info":
            return _info(args)
        if args.command == "formats":
            return _formats(language)
        if args.command == "check-update":
            return _check_update(language)
        if args.command == "serve":
            return _serve(args, language)
        if args.command == "desktop":
            return _desktop(args, language)
        if args.command == "select":
            return _select(args, language)
        if args.command == "integrate":
            return _integrate(args, language)
    except (AdapterError, FileNotFoundError) as exc:
        print(t("cli.error", language, message=exc), file=sys.stderr)
        return 2
    return 0


def _export_language(language: str) -> None:
    """Let child processes (server, desktop shell) inherit the choice.

    Called only by commands that start a long running process, never by the
    one-shot commands, so ``diff`` does not mutate the caller's environment.
    """
    os.environ["DIFFANYDOC_LANG"] = language


def _diff(args: argparse.Namespace, language: str) -> int:
    options = DiffOptions(
        context=args.context,
        case_sensitive=not args.ignore_case,
        collapse_whitespace=args.collapse_whitespace,
        fold_equal=not args.full,
        reflow=args.reflow,
        compare_formatting=args.formatting,
        visual=args.visual,
        visual_dpi=max(50, min(args.visual_dpi, 300)),
        ocr=args.ocr,
        ocr_lang=args.ocr_lang,
    )
    result = compare(args.left, args.right, options)
    fmt = args.format or _infer_format(args.output)

    if fmt == "json":
        payload = json.dumps(result_to_dict(result), ensure_ascii=False, indent=2)
        _emit(payload + "\n", args.output, language)
    elif fmt == "html":
        if args.output:
            write_html_report(result, args.output, language=language)
            print(t("cli.report", language, path=args.output), file=sys.stderr)
        else:
            _emit(render_html(result, language=language), None, language)
    else:
        _emit(_render_text(result, language), args.output, language)

    if args.fail_on_diff and not result.identical:
        return 1
    return 0


def _infer_format(output: Path | None) -> str:
    if output is None:
        return "text"
    suffix = output.suffix.lower()
    if suffix in (".html", ".htm"):
        return "html"
    if suffix == ".json":
        return "json"
    return "html"


def _emit(text: str, output: Path | None, language: str) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(t("cli.written", language, path=output), file=sys.stderr)


_MARKERS = {"equal": " ", "insert": "+", "delete": "-", "replace": "~"}


def _render_text(result, language: str) -> str:
    lines: list[str] = []
    stats = result.stats
    lines.append(f"A: {result.left_path}  ({result.left_kind})")
    lines.append(f"B: {result.right_path}  ({result.right_kind})")
    summary = t(
        "cli.summary",
        language,
        pct=f"{stats.similarity * 100:.1f}",
        added=stats.added,
        removed=stats.removed,
        changed=stats.changed,
    )
    if stats.formatting:
        summary += "  " + t("cli.formatting", language, n=stats.formatting)
    if result.visual is not None:
        summary += "  " + t("cli.visual", language, n=stats.visual_regions)
    lines.append(summary)
    for side, info in (("A", result.left_info), ("B", result.right_info)):
        for warning in (info.warnings if info else []):
            lines.append(f"{side}: " + warning_text(warning, language))
    lines.append("")
    if result.byte_identical:
        lines.append(t("cli.byteIdentical", language))
        return "\n".join(lines) + "\n"
    if result.identical:
        lines.append(t("cli.identical", language))
        return "\n".join(lines) + "\n"

    for row in result.rows:
        if row.hidden_before:
            lines.append(t("cli.hiddenLines", language, n=row.hidden_before))
        if row.left is None and row.right is None:
            continue
        left_number = _gutter(row.left)
        right_number = _gutter(row.right)
        marker = "*" if row.kind == "equal" and row.format_changes else _MARKERS[row.kind]
        text = row.right.text if row.right is not None else row.left.text
        lines.append(f"{marker} {left_number:>5} {right_number:>5} │ {text}")
        if row.cells:
            for cell in row.cells:
                if cell.kind == "equal":
                    continue
                column = cell.right_column or cell.left_column or ""
                where = f"{column}: " if column else ""
                lines.append(
                    f"{'':>13}│   {where}{cell.left if cell.left is not None else '∅'}"
                    f" → {cell.right if cell.right is not None else '∅'}"
                )
        elif row.kind == "replace" and row.left is not None:
            lines.append(f"{'':>13}│   - {row.left.text}")
        if row.format_changes:
            names = ", ".join(t(f"format.{name}", language) for name in row.format_changes)
            lines.append(f"{'':>13}│   {t('cli.formatChange', language, changes=names)}")

    if result.visual:
        changed = [page for page in result.visual if page.regions]
        if changed:
            lines.append("")
            lines.append(t("cli.visualTitle", language))
            for page in changed:
                left = "-" if page.left is None else page.left + 1
                right = "-" if page.right is None else page.right + 1
                lines.append(
                    "  "
                    + t(
                        "cli.visualPage",
                        language,
                        left=left,
                        right=right,
                        n=len(page.regions),
                        pct=f"{page.changed_ratio * 100:.1f}",
                    )
                )
    return "\n".join(lines) + "\n"


def _gutter(line) -> str:
    if line is None:
        return ""
    return line.label if line.label else str(line.number)


def _info(args: argparse.Namespace) -> int:
    document = load(args.file, LoadOptions(ocr=args.ocr, ocr_lang=args.ocr_lang))
    adapter = next(a for a in adapters() if a.name == document.kind)
    payload = {
        "path": str(document.path),
        "adapter": adapter.name,
        "pages": document.page_count,
        "blocks": sum(len(page.blocks) for page in document.pages),
        "characters": document.char_count,
        "meta": document.meta,
        "sections": [
            {
                "index": page.index,
                "label": page.label,
                "source": page.source,
                "blocks": len(page.blocks),
                "tables": sum(1 for b in page.blocks if b.cells is not None),
            }
            for page in document.pages
        ],
        "warnings": document.warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _formats(language: str) -> int:
    print(t("cli.formatsTitle", language))
    for entry in supported_formats():
        print(f"  {entry['name']:<8} {entry['extensions']}")
    print()
    print(t("cli.formatsExtensions", language, value=", ".join(supported_extensions())))
    from .core import ocr

    status = ocr.status()
    if status["available"]:
        print(
            t(
                "cli.ocrAvailable",
                language,
                engine=f"{status['engine']} ({status['version']})",
                langs=", ".join(status["languages"]) or "-",
            )
        )
    else:
        print(t("cli.ocrMissing", language))
    return 0


def _check_update(language: str) -> int:
    from .updates import check

    info = check()
    if info.status == "update":
        print(t("updates.available", language, version=info.latest, current=info.current))
        print(info.url)
        return 0
    if info.status == "latest":
        print(t("updates.latest", language, version=info.current))
        return 0
    if info.status == "no_releases":
        print(t("updates.noReleases", language))
        return 0
    print(t("updates.failed", language, message=info.message or ""), file=sys.stderr)
    return 2


def _serve(args: argparse.Namespace, language: str) -> int:
    try:
        from .web.server import run
    except ImportError as exc:
        print(
            "the web UI needs extra dependencies:\n  pip install 'diffanydoc[web]'",
            file=sys.stderr,
        )
        print(f"({exc})", file=sys.stderr)
        return 2
    _export_language(language)
    run(host=args.host, port=args.port, reload=args.reload)
    return 0


def _desktop(args: argparse.Namespace, language: str) -> int:
    try:
        from .desktop import run_desktop
    except ImportError as exc:
        print(
            "the desktop shell needs extra dependencies:\n"
            "  pip install 'diffanydoc[desktop]'",
            file=sys.stderr,
        )
        print(f"({exc})", file=sys.stderr)
        return 2
    missing = [path for path in args.files if not path.exists()]
    if missing:
        print(t("cli.error", language, message=missing[0]), file=sys.stderr)
        return 2
    _export_language(language)
    return run_desktop(
        args.files,
        width=args.width,
        height=args.height,
        debug=args.debug,
        language=language,
    )


def _select(args: argparse.Namespace, language: str) -> int:
    """File-manager entry point: reuse the running window, otherwise open one."""
    path = args.path.expanduser().resolve()
    if not path.is_file():
        print(t("cli.error", language, message=path), file=sys.stderr)
        return 2

    from .session import send_selection

    if send_selection(args.slot, path):
        return 0

    try:
        from .desktop import run_desktop
    except ImportError as exc:
        print(
            "the desktop shell needs extra dependencies:\n"
            "  pip install 'diffanydoc[desktop]'",
            file=sys.stderr,
        )
        print(f"({exc})", file=sys.stderr)
        return 2
    _export_language(language)
    return run_desktop([path], slots=[args.slot], language=language)


def _integrate(args: argparse.Namespace, language: str) -> int:
    from . import integrate

    try:
        if args.action == "install":
            items = integrate.install(language)
        else:
            items = integrate.uninstall(language)
    except NotImplementedError:
        print(t("integrate.unsupported", language), file=sys.stderr)
        return 2
    except OSError as exc:
        print(
            t(
                "integrate.failed",
                language,
                path=getattr(exc, "filename", "") or "",
                error=exc,
            ),
            file=sys.stderr,
        )
        return 2

    if args.action == "install":
        print(t("integrate.installed", language))
    elif items:
        print(t("integrate.removed", language))
    else:
        print(t("integrate.nothing", language))
    for item in items:
        print(f"  {item}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
