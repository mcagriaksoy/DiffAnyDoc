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
from .core.adapters import AdapterError, adapters, load, supported_extensions
from .core.diff import DiffOptions, compare, supported_formats
from .core.folder import compare_folders
from .core.ocr import OcrError
from .core.report.html import render_html, write_html_report
from .core.report.json import result_to_dict
from .core.report.pdf import render_pdf, write_pdf_report
from .i18n import available_languages, resolve_language, t


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
        choices=("html", "json", "text", "pdf"),
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
        "--visual",
        action="store_true",
        help="also compare rendered PDF pages pixel by pixel",
    )
    diff.add_argument(
        "--ocr",
        action="store_true",
        help="OCR pages without a text layer (scanned PDFs and images; uses RapidOCR)",
    )
    diff.add_argument(
        "--ocr-lang",
        default="eng",
        metavar="LANG",
        help="OCR language(s), e.g. eng or tur+eng (eng)",
    )
    diff.add_argument(
        "--format-diff",
        action="store_true",
        help="also report formatting/style differences (font, size, bold, italic)",
    )
    diff.add_argument(
        "--tolerance",
        type=float,
        default=None,
        metavar="FLOAT",
        help="numeric difference tolerance (e.g. 0.01 for rounding)",
    )
    diff.add_argument(
        "--no-fast-check",
        action="store_true",
        help="always parse both files even when their SHA-256 checksums match",
    )
    diff.add_argument(
        "--fail-on-diff",
        action="store_true",
        help="exit with code 1 when differences exist (CI / git hooks)",
    )

    info = subparsers.add_parser("info", help="show the parsed outline of a file")
    info.add_argument("file", type=Path)

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

    ctx = subparsers.add_parser(
        "context-action", help="handle single-entry file-manager context menu action"
    )
    ctx.add_argument("files", nargs="*", type=Path, help="file(s) selected from context menu")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    language = resolve_language(args.lang)
    try:
        if args.command == "diff":
            return _diff(args, language)
        if args.command == "info":
            return _info(args)
        if args.command == "check-update":
            return _check_update(language)
        if args.command == "formats":
            return _formats(language)
        if args.command == "serve":
            return _serve(args, language)
        if args.command == "desktop":
            return _desktop(args, language)
        if args.command == "select":
            return _select(args, language)
        if args.command == "integrate":
            return _integrate(args, language)
        if args.command == "context-action":
            return _context_action(args, language)
    except (AdapterError, FileNotFoundError, OcrError) as exc:
        print(t("cli.error", language, message=exc), file=sys.stderr)
        return 2
    return 0


def _export_language(language: str) -> None:
    """Let child processes (server, desktop shell) inherit the choice.

    Called only by commands that start a long running process, never by the
    one-shot commands, so ``diff`` does not mutate the caller's environment.
    """
    os.environ["DIFFANYDOC_LANG"] = language


def _diff_folders(args: argparse.Namespace, language: str) -> int:
    res = compare_folders(args.left, args.right)
    fmt = args.format or _infer_format(args.output)
    if fmt == "json":
        payload = json.dumps(res.as_dict(), ensure_ascii=False, indent=2)
        _emit(payload + "\n", args.output, language)
    else:
        out_lines = [
            f"📁 {t('stats.docA', language)}: {res.left_path}",
            f"📁 {t('stats.docB', language)}: {res.right_path}",
            "═" * 65,
            f"  [=] {t('folder.identical', language)}: {res.identical_count}",
            f"  [~] {t('folder.modified', language)}:  {res.modified_count}",
            f"  [+] {t('folder.added', language)}:     {res.added_count}",
            f"  [-] {t('folder.removed', language)}:   {res.removed_count}",
            "─" * 65,
        ]
        for item in res.items:
            if item.status == "identical":
                continue
            mark = "~" if item.status == "modified" else ("+" if item.status == "added" else "-")
            out_lines.append(f"  {mark} {item.rel_path} ({item.status})")
        _emit("\n".join(out_lines) + "\n", args.output, language)

    if args.fail_on_diff and not res.identical:
        return 1
    return 0


def _diff(args: argparse.Namespace, language: str) -> int:
    if args.left.is_dir() and args.right.is_dir():
        return _diff_folders(args, language)

    options = DiffOptions(
        context=args.context,
        case_sensitive=not args.ignore_case,
        compare_formatting=args.format_diff,
        fold_equal=not args.full,
        fast_check=not args.no_fast_check,
        visual=args.visual,
        ocr=args.ocr,
        ocr_language=args.ocr_lang,
        numeric_tolerance=args.tolerance,
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
    elif fmt == "pdf":
        if args.output:
            write_pdf_report(result, args.output, language=language)
            print(t("cli.report", language, path=args.output), file=sys.stderr)
        else:
            sys.stdout.buffer.write(render_pdf(result, language=language))
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
    if suffix == ".pdf":
        return "pdf"
    return "html"


def _emit(text: str, output: Path | None, language: str) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(t("cli.written", language, path=output), file=sys.stderr)


def _render_text(result, language: str) -> str:
    lines: list[str] = []
    stats = result.stats
    lines.append(f"A: {result.left_path}  ({result.left_kind})")
    lines.append(f"B: {result.right_path}  ({result.right_kind})")
    lines.append(
        t(
            "cli.summary",
            language,
            pct=f"{stats.similarity * 100:.1f}",
            added=stats.added,
            removed=stats.removed,
            changed=stats.changed,
        )
    )
    lines.append("")

    ocr = result.ocr
    if ocr is not None and ocr.pages:
        lines.append(
            t(
                "cli.ocr",
                language,
                pages=ocr.pages,
                cached=ocr.cached,
                words=ocr.words,
                lang=ocr.language,
            )
        )
        lines.append("")

    visual = result.visual
    if visual is not None and visual.compared:
        lines.append(
            t(
                "cli.visual",
                language,
                pct=f"{visual.similarity * 100:.1f}",
                changed=visual.changed_pages,
                pages=visual.compared,
                regions=visual.region_count,
            )
        )
        lines.append("")

    if result.identical:
        lines.append(t("cli.identical", language))
        return "\n".join(lines) + "\n"

    for row in result.rows:
        if row.hidden_before:
            lines.append(t("cli.hiddenLines", language, n=row.hidden_before))
        left_number = row.left.number if row.left else ""
        right_number = row.right.number if row.right else ""
        marker = {"equal": " ", "insert": "+", "delete": "-", "replace": "~"}[row.kind]
        text = row.right.text if row.right is not None else row.left.text
        lines.append(f"{marker} {str(left_number):>4} {str(right_number):>4} │ {text}")
    return "\n".join(lines) + "\n"


def _info(args: argparse.Namespace) -> int:
    document = load(args.file)
    adapter = next((a for a in adapters() if a.name == document.kind), None)
    adapter_name = adapter.name if adapter else document.kind
    payload = {
        "path": str(document.path),
        "adapter": adapter_name,
        "pages": document.page_count,
        "blocks": sum(len(page.blocks) for page in document.pages),
        "characters": document.char_count,
        "meta": document.meta,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _formats(language: str) -> int:
    print(t("cli.formatsTitle", language))
    for entry in supported_formats():
        print(f"  {entry['name']:<8} {entry['extensions']}")
    print()
    print(t("cli.formatsExtensions", language, value=", ".join(supported_extensions())))
    return 0


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


def _context_action(args: argparse.Namespace, language: str) -> int:
    """Smart single-line context menu action.

    - If 2+ files are provided: immediately launch comparison.
    - If 1 file is provided:
        - If a different file was previously selected as the left file: launch comparison and reset.
        - Otherwise: store this file as the pending left file, notify the user, and update menu label.
    """
    from . import integrate

    raw_files = [Path(p).expanduser().resolve() for p in args.files]
    files = [p for p in raw_files if p.exists()]
    if not files:
        return 0

    if len(files) >= 2:
        integrate.clear_pending_selection(language)
        return _launch_comparison(files[0], files[1], language)

    current = files[0]
    pending = integrate.get_pending_selection()

    if pending and pending.exists() and pending != current:
        integrate.clear_pending_selection(language)
        return _launch_comparison(pending, current, language)

    integrate.set_pending_selection(current, language)
    from .session import send_selection

    send_selection("left", current)
    integrate.notify_selection(current, language)
    return 0


def _launch_comparison(left: Path, right: Path, language: str) -> int:
    """Send both files to running window or open a new desktop window."""
    from .session import send_selection

    if send_selection("left", left) and send_selection("right", right):
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
    return run_desktop([left, right], language=language)


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


def _check_update(language: str) -> int:
    from .updates import check_for_updates

    info = check_for_updates()
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
