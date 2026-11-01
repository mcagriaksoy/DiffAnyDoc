"""Self-contained HTML report: no JS dependencies, works offline, prints well."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from ...i18n import resolve_language, t
from ..model import DiffResult, Segment

_CSS = """
:root{
  color-scheme:light dark;
  --window-bg-color:#fafafb; --view-bg-color:#ffffff; --headerbar-bg-color:#ffffff;
  --border-color:rgba(0,0,0,.12); --text-color:#1d1d20; --dim-label-color:#6b7280;
  --accent-color:#3584e4; --success-color:#1c7d4d; --warning-color:#8a6100;
  --error-color:#b3261e; --hover-tint:rgba(0,0,0,.06);
  --diff-add-bg:rgba(38,162,105,.12); --diff-del-bg:rgba(224,27,36,.10);
  --diff-mod-bg:rgba(232,168,0,.14); --diff-add-strong:rgba(38,162,105,.24);
  --diff-del-strong:rgba(224,27,36,.20);
  --font-ui:system-ui,-apple-system,"Segoe UI Variable Text","Segoe UI",Cantarell,
    Ubuntu,Roboto,"Noto Sans",sans-serif;
  --font-mono:ui-monospace,"Cascadia Mono","SF Mono","JetBrains Mono",Menlo,Consolas,
    "Noto Sans Mono",monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    --window-bg-color:#1d1d20; --view-bg-color:#26262a; --headerbar-bg-color:#303034;
    --border-color:rgba(255,255,255,.12); --text-color:#ffffff; --dim-label-color:#b0b0b6;
    --accent-color:#78aeed; --success-color:#7ee2a8; --warning-color:#ffd479;
    --error-color:#ff9d9d; --hover-tint:rgba(255,255,255,.08);
    --diff-add-bg:rgba(46,194,126,.16); --diff-del-bg:rgba(255,99,99,.14);
    --diff-mod-bg:rgba(255,212,121,.14); --diff-add-strong:rgba(46,194,126,.30);
    --diff-del-strong:rgba(255,99,99,.26);
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--window-bg-color);color:var(--text-color);
  font:14.5px/1.5 var(--font-ui);-webkit-font-smoothing:antialiased}
a{color:var(--accent-color)}
:focus-visible{outline:2px solid var(--accent-color);outline-offset:2px}

/* One header, two rows: identity + view switch, then files + flat stats. */
.report-header{padding:18px 24px 12px;background:var(--headerbar-bg-color);
  border-bottom:1px solid var(--border-color)}
.head-row{display:flex;align-items:center;justify-content:space-between;gap:18px;
  flex-wrap:wrap}
.brand{display:flex;align-items:baseline;gap:8px;font-size:15px;font-weight:700}
.brand span{color:var(--dim-label-color);font-size:12px;font-weight:400}
.view-switch{display:inline-flex;gap:2px;padding:3px;border-radius:6px;
  background:var(--hover-tint)}
.view-switch button{height:26px;padding:0 12px;border:0;border-radius:4px;
  background:transparent;color:var(--dim-label-color);font:inherit;font-size:13px;
  cursor:pointer}
.view-switch button:hover{color:var(--text-color)}
.view-switch button[aria-pressed="true"]{background:var(--view-bg-color);
  color:var(--text-color);font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.14)}
.files{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:12px;
  color:var(--dim-label-color);font-size:12px}
.file{display:inline-flex;align-items:center;gap:6px;min-width:0}
.file b{max-width:38ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:var(--text-color);font-size:13px;font-weight:600}
.badge{display:inline-flex;align-items:center;justify-content:center;width:18px;
  height:18px;border:1px solid var(--border-color);border-radius:4px;color:var(--dim-label-color);
  font-size:10px;font-weight:700;flex:none}
.stats{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:10px;
  color:var(--dim-label-color);font-size:12px}
.stat b{color:var(--text-color);font-weight:600}
.stat.add b{color:var(--success-color)}
.stat.del b{color:var(--error-color)}
.stat.mod b{color:var(--warning-color)}

main{padding:0 0 36px}
table{width:100%;border-collapse:collapse;table-layout:fixed}
thead th{position:sticky;top:0;z-index:1;background:var(--view-bg-color);
  border-bottom:1px solid var(--border-color);text-align:left;padding:6px 12px;
  color:var(--dim-label-color);font-size:12px;font-weight:600}
thead th:first-child{border-right:1px solid var(--border-color)}
td{padding:1px 12px;vertical-align:top;font-family:var(--font-mono);font-size:12.5px;
  white-space:pre-wrap;word-break:break-word}
td:first-child{border-right:1px solid var(--border-color)}
.gutter{display:inline-block;width:42px;padding-right:10px;color:var(--dim-label-color);
  text-align:right;user-select:none;font-size:11.5px}
.page{display:inline-block;min-width:40px;margin-right:8px;padding:0 5px;border-radius:4px;
  background:var(--window-bg-color);color:var(--dim-label-color);font-size:10.5px;
  text-align:center}
.page:empty{background:transparent}
tr.add td:nth-child(2){background:var(--diff-add-bg);
  box-shadow:inset 2px 0 0 var(--success-color)}
tr.del td:nth-child(1){background:var(--diff-del-bg);
  box-shadow:inset 2px 0 0 var(--error-color)}
tr.mod td{background:var(--diff-mod-bg);
  box-shadow:inset 2px 0 0 var(--warning-color)}
del{background:var(--diff-del-strong);color:inherit;border-radius:2px;
  text-decoration:line-through;text-decoration-thickness:1px}
ins{background:var(--diff-add-strong);color:inherit;border-radius:2px;text-decoration:none}
.gap td{background:var(--window-bg-color);border-top:1px solid var(--border-color);
  border-bottom:1px solid var(--border-color);color:var(--dim-label-color);
  font-family:inherit;font-size:12px;text-align:center;padding:4px}
.empty{color:var(--dim-label-color);text-align:center;padding:56px 20px;font-family:inherit}
body.only-diff tr.equal,body.only-diff tr.gap{display:none}
footer{color:var(--dim-label-color);font-size:12px;text-align:center;padding:18px}

@media print{
  :root{
    color-scheme:light;
    --window-bg-color:#ffffff; --view-bg-color:#ffffff; --headerbar-bg-color:#ffffff;
    --border-color:rgba(0,0,0,.15); --text-color:#1d1d20; --dim-label-color:#4b5563;
    --diff-add-bg:#e6f7ec; --diff-del-bg:#fdeaea; --diff-mod-bg:#fff7e0;
    --diff-add-strong:#bfe8cf; --diff-del-strong:#f5c9c9;
    --success-color:#0f6b36; --warning-color:#7a5200; --error-color:#a11a1a;
  }
  body{background:#fff}
  thead th{position:static}
  .view-switch{display:none}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""

_JS = """
document.querySelectorAll('[data-toggle]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var only = btn.dataset.toggle === 'diff';
    document.body.classList.toggle('only-diff', only);
    document.querySelectorAll('[data-toggle]').forEach(function (other) {
      other.setAttribute('aria-pressed', String(other === btn));
    });
  });
});
"""


def render_html(
    result: DiffResult,
    *,
    title: str | None = None,
    language: str | None = None,
) -> str:
    lang = resolve_language(language)
    document_title = title or t(
        "report.title", lang, left=result.left_path.name, right=result.right_path.name
    )
    stats = result.stats
    last_page = {"left": -1, "right": -1}
    body_rows = "\n".join(
        _row_html(row, lang, last_page) for row in result.rows
    )
    if not result.rows:
        body_rows = (
            '<tr><td class="empty" colspan="2">'
            f"{html.escape(t('report.empty', lang))}"
            "</td></tr>"
        )

    percent = f"{stats.similarity * 100:.1f}%"
    add_class = " add" if stats.added else ""
    del_class = " del" if stats.removed else ""
    mod_class = " mod" if stats.changed else ""
    visual_stats = _visual_stats(result, lang)
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{html.escape(document_title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header class="report-header">
  <div class="head-row">
    <div class="brand">DiffAnyDoc <span>{html.escape(t("report.brand", lang))}</span></div>
    <div class="view-switch" role="group" aria-label="{html.escape(t("report.view", lang))}">
      <button type="button" data-toggle="all" aria-pressed="true">{html.escape(t("report.all", lang))}</button>
      <button type="button" data-toggle="diff" aria-pressed="false">{html.escape(t("report.onlyDiff", lang))}</button>
    </div>
  </div>
  <div class="files">
    <span class="file"><span class="badge">A</span><b>{html.escape(result.left_path.name)}</b><span>· {result.left_kind}</span></span>
    <span class="file"><span class="badge">B</span><b>{html.escape(result.right_path.name)}</b><span>· {result.right_kind}</span></span>
  </div>
  <div class="stats">
    <span class="stat">{html.escape(t("report.similarity", lang))} <b>{percent}</b></span>
    <span class="stat{add_class}"><b>+{stats.added}</b> {html.escape(t("stats.added", lang))}</span>
    <span class="stat{del_class}"><b>−{stats.removed}</b> {html.escape(t("stats.removed", lang))}</span>
    <span class="stat{mod_class}"><b>~{stats.changed}</b> {html.escape(t("stats.changed", lang))}</span>
    <span class="stat">{html.escape(t("report.lines", lang, left=stats.left_lines, right=stats.right_lines))}</span>
    <span class="stat">{html.escape(t("report.pageMap", lang, n=len(result.page_map)))}</span>
    {visual_stats}
  </div>
</header>
<main>
<table>
  <thead>
    <tr>
      <th>{html.escape(result.left_path.name)}</th>
      <th>{html.escape(result.right_path.name)}</th>
    </tr>
  </thead>
  <tbody>
{body_rows}
  </tbody>
</table>
</main>
<footer>{html.escape(t("report.footer", lang))}</footer>
<script>{_JS}</script>
</body>
</html>
"""


def _visual_stats(result: DiffResult, lang: str) -> str:
    visual = result.visual
    if visual is None or not visual.compared:
        return ""
    parts = [
        f'<span class="stat">{html.escape(t("report.visual", lang))} '
        f"<b>{visual.similarity * 100:.1f}%</b></span>",
        f'<span class="stat">{html.escape(t("report.visualPages", lang, changed=visual.changed_pages, total=visual.compared))}</span>',
    ]
    if visual.truncated:
        parts.append(
            f'<span class="stat">{html.escape(t("report.visualTruncated", lang))}</span>'
        )
    return "".join(parts)


_ROW_CLASS = {"equal": "equal", "insert": "add", "delete": "del", "replace": "mod"}


def _row_html(row: Any, lang: str, last_page: dict[str, int]) -> str:
    parts: list[str] = []
    if row.hidden_before:
        label = html.escape(t("gap.hidden", lang, n=row.hidden_before))
        parts.append(f'<tr class="gap"><td colspan="2">⋯ {label} ⋯</td></tr>')

    left_cells = _cell(row.left, row.left_inline, lang, last_page["left"])
    right_cells = _cell(row.right, row.right_inline, lang, last_page["right"])
    if row.left is not None:
        last_page["left"] = row.left.page
    if row.right is not None:
        last_page["right"] = row.right.page
    parts.append(
        f'<tr class="{_ROW_CLASS[row.kind]}">{left_cells}{right_cells}</tr>'
    )
    return "\n".join(parts)


def _cell(
    line: Any, inline: list[Segment] | None, lang: str, previous_page: int
) -> str:
    if line is None:
        return "<td></td>"
    gutter = f'<span class="gutter">{_row_number(line)}</span>'
    label = "" if line.page == previous_page else t("page.label", lang, n=line.page + 1)
    page = f'<span class="page">{html.escape(label)}</span>'
    text = _inline_html(inline) if inline else html.escape(line.text, quote=False)
    return f'<td>{gutter}{page}<span class="text">{text}</span></td>'


def _inline_html(segments: list[Segment]) -> str:
    out: list[str] = []
    for segment in segments:
        text = html.escape(segment.text, quote=False)
        if segment.kind == "delete":
            out.append(f"<del>{text}</del>")
        elif segment.kind == "insert":
            out.append(f"<ins>{text}</ins>")
        else:
            out.append(text)
    return "".join(out)


def _row_number(line: Any) -> str:
    number = getattr(line, "number", None)
    if number is not None:
        return str(number)
    return "·"


def write_html_report(
    result: DiffResult, path: str | Path, *, language: str | None = None
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(result, language=language), encoding="utf-8")
    return path
