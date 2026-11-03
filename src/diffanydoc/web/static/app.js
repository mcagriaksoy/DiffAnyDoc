"use strict";

const state = {
  files: { left: null, right: null },
  comparison: null,
  mode: "text",
  zoom: 1,
  version: "",
  isDesktop: false,
  changes: [],
  changeIndex: -1,
  comparing: false,
  /* Visual comparison per page pair: { [pairIndex]: page }, filled lazily. */
  visual: {},
  visualLoading: null,
  capabilities: null,
};

/* Present when the page runs inside the native pywebview shell. */
const desktop = {
  available: false,
  paths: { left: null, right: null },
};

const LANG_KEY = "diffanydoc:lang";
const LANGUAGE_NAMES = { en: "English", tr: "Türkçe" };

const i18n = {
  lang: "en",
  languages: ["en", "tr"],
  strings: {},
  t(key, values) {
    let text = Object.prototype.hasOwnProperty.call(this.strings, key)
      ? this.strings[key]
      : key;
    if (values) {
      for (const [name, value] of Object.entries(values)) {
        text = text.replaceAll(`{${name}}`, String(value));
      }
    }
    return text;
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

/* ---------- small DOM helper ---------- */
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/* ---------- language ---------- */
function preferredLanguage() {
  const fromUrl = new URLSearchParams(location.search).get("lang");
  if (fromUrl) return fromUrl;
  const saved = localStorage.getItem(LANG_KEY);
  if (saved) return saved;
  return "en";
}

async function loadLanguage(requested) {
  try {
    const response = await fetch(`/api/i18n/${encodeURIComponent(requested)}`);
    if (!response.ok) throw new Error("i18n");
    const payload = await response.json();
    i18n.lang = payload.language;
    i18n.strings = payload.strings || {};
  } catch (_) {
    i18n.lang = "en";
    i18n.strings = {};
  }

  try {
    const response = await fetch("/api/i18n/languages");
    if (response.ok) {
      const payload = await response.json();
      if (Array.isArray(payload.languages) && payload.languages.length) {
        i18n.languages = payload.languages;
      }
    }
  } catch (_) {
    /* keep the built-in list */
  }

  document.documentElement.lang = i18n.lang;
  applyTranslations();
  renderLanguageMenu();
  renderVersion();
  renderOcrNote();

  if (state.comparison) renderResult();
}

function applyTranslations() {
  for (const node of $$("[data-i18n]")) {
    node.textContent = i18n.t(node.dataset.i18n);
  }
  for (const node of $$("[data-i18n-title]")) {
    node.title = i18n.t(node.dataset.i18nTitle);
  }
  for (const node of $$("[data-i18n-aria-label]")) {
    node.setAttribute("aria-label", i18n.t(node.dataset.i18nAriaLabel));
  }
}

function renderLanguageMenu() {
  const menu = $("#lang-menu");
  const current = $("#lang-current");
  if (current) current.textContent = i18n.lang.toUpperCase();
  const button = $("#lang-button");
  if (button) {
    button.setAttribute(
      "aria-label",
      `${i18n.t("lang.label")}: ${i18n.lang.toUpperCase()}`
    );
  }
  if (!menu) return;
  menu.replaceChildren();
  for (const code of i18n.languages) {
    const item = el(
      "button",
      {
        class: `menu-item${code === i18n.lang ? " active" : ""}`,
        role: "menuitemradio",
        "aria-checked": String(code === i18n.lang),
        type: "button",
      },
      [
        el("span", { text: LANGUAGE_NAMES[code] || code.toUpperCase() }),
        el("span", { class: "lang-code", text: code.toUpperCase() }),
      ]
    );
    item.addEventListener("click", async () => {
      closeMenus();
      localStorage.setItem(LANG_KEY, code);
      await loadLanguage(code);
    });
    menu.append(item);
  }
}

/* ---------- menus ---------- */
function closeMenus() {
  for (const menu of $$(".menu")) menu.hidden = true;
  for (const button of $$("[data-menu]")) {
    button.setAttribute("aria-expanded", "false");
  }
}

function setupMenus() {
  for (const button of $$("[data-menu]")) {
    const menu = document.getElementById(button.dataset.menu);
    if (!menu) continue;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = menu.hidden;
      closeMenus();
      if (open) {
        menu.hidden = false;
        button.setAttribute("aria-expanded", "true");
      }
    });
    menu.addEventListener("click", (event) => event.stopPropagation());
  }
  document.addEventListener("click", closeMenus);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenus();
  });
}

/* ---------- version in the overflow menu ---------- */
function renderVersion() {
  const node = $("#version");
  if (!node || !state.version) return;
  const suffix = state.isDesktop ? ` · ${i18n.t("app.versionDesktop")}` : "";
  node.textContent = `DiffAnyDoc v${state.version}${suffix}`;
  const about = $("#about-version");
  if (about) {
    about.textContent = i18n.t("about.version", { version: state.version });
  }
}

/* ---------- dialogs (About / License / Updates) ---------- */
function fillAbout() {
  const node = $("#about-version");
  if (node && state.version) {
    node.textContent = i18n.t("about.version", { version: state.version });
  }
}

function fillUpdates() {
  const node = $("#updates-current");
  if (node && state.version) {
    node.textContent = i18n.t("updates.current", { version: state.version });
  }
  $("#updates-status").textContent = i18n.t("updates.privacy");
  $("#updates-link").hidden = true;
}

let licenseLoaded = false;

async function openLicense() {
  closeMenus();
  const dialog = $("#license-dialog");
  if (!dialog.open) dialog.showModal();
  if (licenseLoaded) return;

  const body = $("#license-text");
  body.textContent = i18n.t("license.loading");
  try {
    const response = await fetch("/static/gpl-3.0.txt");
    if (!response.ok) throw new Error("license");
    body.textContent = await response.text();
    licenseLoaded = true;
  } catch (_) {
    body.textContent = i18n.t("license.unavailable");
  }
}

function setupDialogs() {
  for (const dialog of $$("dialog")) {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    for (const button of dialog.querySelectorAll("[data-close]")) {
      button.addEventListener("click", () => dialog.close());
    }
  }

  $("#about").addEventListener("click", () => {
    closeMenus();
    fillAbout();
    $("#about-dialog").showModal();
  });
  $("#about-license").addEventListener("click", () => {
    $("#about-dialog").close();
    openLicense();
  });
  $("#license").addEventListener("click", openLicense);
  $("#updates").addEventListener("click", () => {
    closeMenus();
    fillUpdates();
    $("#updates-dialog").showModal();
  });
  $("#updates-check").addEventListener("click", checkUpdates);
  $("#updates-link").addEventListener("click", (event) => {
    if (!desktop.available) return;
    event.preventDefault();
    window.pywebview.api.open_external($("#updates-link").href);
  });
}

/* ---------- system accent ---------- */
function textOn(hex) {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16) / 255;
  const g = parseInt(value.slice(2, 4), 16) / 255;
  const b = parseInt(value.slice(4, 6), 16) / 255;
  const channel = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  return luminance > 0.55 ? "#1d1d20" : "#ffffff";
}

async function loadTheme() {
  try {
    const response = await fetch("/api/system/theme");
    if (!response.ok) return;
    const theme = await response.json();
    const accent = theme && theme.accent;
    if (!accent || !/^#[0-9a-f]{6}$/i.test(accent)) return;
    const root = document.documentElement.style;
    root.setProperty("--accent-bg-color", accent);
    root.setProperty("--accent-color", accent);
    root.setProperty("--accent-fg-color", textOn(accent));
  } catch (_) {
    /* the CSS fallback accent is fine */
  }
}

/* ---------- upload ---------- */
function setupDropZones() {
  $$(".drop").forEach((zone) => {
    const side = zone.dataset.side;
    const input = zone.querySelector("input[type=file]");

    input.addEventListener("change", () => {
      if (input.files && input.files[0]) setFile(side, input.files[0]);
    });

    ["dragenter", "dragover"].forEach((event) =>
      zone.addEventListener(event, (e) => {
        e.preventDefault();
        zone.classList.add("dragover");
      })
    );
    ["dragleave", "dragend", "drop"].forEach((event) =>
      zone.addEventListener(event, (e) => {
        e.preventDefault();
        zone.classList.remove("dragover");
      })
    );

    zone.addEventListener("drop", (e) => {
      const file = e.dataTransfer && e.dataTransfer.files[0];
      if (!file) return;
      try {
        input.files = e.dataTransfer.files;
      } catch (_) {
        /* some browsers refuse programmatic assignment; state is what matters */
      }
      setFile(side, file);
    });

    // Keyboard access: the drop zone behaves like a button.
    zone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        chooseFile(side);
      }
    });

    // In the desktop shell, use the native file dialog instead of <input>.
    zone.addEventListener("click", (event) => {
      if (!desktop.available) return;
      event.preventDefault();
      chooseFile(side);
    });
  });
}

function basename(path) {
  return String(path).split(/[\\/]/).pop() || String(path);
}

function showPath(side, path) {
  const zone = document.querySelector(`.drop[data-side="${side}"]`);
  if (!zone) return;
  zone.classList.add("filled");
  const chip = zone.querySelector(".file-chip");
  chip.hidden = false;
  chip.textContent = basename(path);
  chip.title = path;
}

async function chooseFile(side) {
  if (!desktop.available) {
    document.querySelector(`.drop[data-side="${side}"] input[type=file]`).click();
    return;
  }
  try {
    const path = await window.pywebview.api.pick_file(i18n.lang);
    if (!path) return;
    desktop.paths[side] = path;
    showPath(side, path);
    updateCompareButton();
  } catch (error) {
    showError(error && error.message ? error.message : String(error));
  }
}

function setFile(side, file) {
  state.files[side] = file;
  const zone = document.querySelector(`.drop[data-side="${side}"]`);
  zone.classList.add("filled");
  const chip = zone.querySelector(".file-chip");
  chip.hidden = false;
  chip.textContent = `${file.name} · ${formatBytes(file.size)}`;
  updateCompareButton();
}

function isReady() {
  if (desktop.available && desktop.paths.left && desktop.paths.right) return true;
  return Boolean(state.files.left && state.files.right);
}

function updateCompareButton() {
  $("#compare").disabled = !isReady();
}

function showError(message) {
  const node = $("#error");
  node.textContent = message;
  node.hidden = false;
}

function hideError() {
  $("#error").hidden = true;
}

/* ---------- comparison ---------- */
async function runComparison() {
  if (!isReady() || state.comparing) return;
  state.comparing = true;
  hideError();

  const button = $("#compare");
  const spinner = button.querySelector(".spinner");
  button.disabled = true;
  spinner.hidden = false;

  try {
    let response;
    const caseSensitive = !$("#opt-case").checked;
    const collapseWhitespace = $("#opt-space").checked;
    const reflow = $("#opt-reflow").checked;
    const formatting = $("#opt-format").checked;
    const ocrMode = $("#opt-ocr").value;
    if (desktop.available && desktop.paths.left && desktop.paths.right) {
      response = await fetch("/api/compare-paths", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          left: desktop.paths.left,
          right: desktop.paths.right,
          case_sensitive: caseSensitive,
          collapse_whitespace: collapseWhitespace,
          reflow,
          compare_formatting: formatting,
          ocr: ocrMode,
          fold_equal: false,
          context: 3,
        }),
      });
    } else {
      const form = new FormData();
      form.append("left", state.files.left);
      form.append("right", state.files.right);
      form.append("case_sensitive", String(caseSensitive));
      form.append("collapse_whitespace", String(collapseWhitespace));
      form.append("reflow", String(reflow));
      form.append("compare_formatting", String(formatting));
      form.append("ocr_mode", ocrMode);
      form.append("fold_equal", "false");
      form.append("context", "3");
      response = await fetch("/api/compare", { method: "POST", body: form });
    }
    if (!response.ok) throw new Error(await readError(response));
    setComparison(await response.json());
    renderResult();
  } catch (error) {
    showError(error.message || i18n.t("error.generic"));
  } finally {
    spinner.hidden = true;
    state.comparing = false;
    updateCompareButton();
  }
}

async function readError(response) {
  try {
    const payload = await response.json();
    if (payload.detail) return payload.detail;
  } catch (_) {
    /* fall through */
  }
  return `${response.status} ${response.statusText}`;
}

/* ---------- result shell ---------- */
function setComparison(data) {
  state.comparison = data;
  state.visual = {};
  state.visualLoading = null;
  for (const page of data.visual || []) state.visual[page.pair] = page;
  // Images and scans: the pixel comparison is the main signal, show it.
  $("#show-visual").checked = Array.isArray(data.visual);
}

function bothRenderable(data) {
  return Boolean(data.renderable.left && data.renderable.right);
}

function viewUrl(data) {
  const view = state.mode !== "text" ? `&view=${state.mode}` : "";
  return `${location.pathname}?id=${data.id}${view}&lang=${i18n.lang}`;
}

function kindLabel(side) {
  const info = state.comparison[side];
  const kind = info.kind;
  const meta = info.meta || {};
  if (kind === "xlsx") return `${kind} · ${i18n.t("meta.sheets", { n: meta.sheets || info.pages })}`;
  if (kind === "docx") {
    const parts = [kind];
    if (meta.tables) parts.push(i18n.t("meta.tables", { n: meta.tables }));
    return parts.join(" · ");
  }
  if (kind === "text") return meta.table ? `${kind} · ${i18n.t("meta.table")}` : kind;
  return `${kind} · ${i18n.t("meta.pages", { n: info.pages })}`;
}

function renderResult() {
  const data = state.comparison;
  $("#upload-view").hidden = true;
  $("#result-view").hidden = false;
  $("#view-tabs").hidden = false;

  for (const node of $$("[data-result-only]")) node.hidden = false;

  if (data.id) history.replaceState(null, "", viewUrl(data));

  $("#name-left").textContent = data.left.name;
  $("#name-right").textContent = data.right.name;
  $("#meta-left").textContent = kindLabel("left");
  $("#meta-right").textContent = kindLabel("right");

  renderStats(data.stats);
  renderWarnings(data);

  const canRender = data.renderable.left || data.renderable.right;
  const canOverlay = bothRenderable(data);
  $("#tab-pages").disabled = !canRender;
  $("#tab-overlay").disabled = !canOverlay;
  if (!canRender && state.mode === "pages") state.mode = "text";
  if (!canOverlay && state.mode === "overlay") state.mode = "text";

  $("#export").href = `/api/compare/${data.id}/report?lang=${i18n.lang}`;

  renderText();
  renderPages();
  $("#overlay-view").replaceChildren();
  setMode(state.mode);
  window.scrollTo({ top: 0 });
}

function warningMessage(warning) {
  const pages = (warning.pages || []).map((p) => p + 1);
  const values = { ...warning, n: pages.length, pages: pages.slice(0, 12).join(", ") };
  return i18n.t(`warning.${warning.code}`, values);
}

function renderWarnings(data) {
  const node = $("#warnings");
  const items = [];
  if (data.byte_identical) items.push(el("p", { text: i18n.t("result.byteIdentical") }));
  for (const side of ["left", "right"]) {
    for (const warning of data[side].warnings || []) {
      items.push(
        el("p", {}, [
          el("span", { class: "side-badge", text: side === "left" ? "A" : "B" }),
          " ",
          warningMessage(warning),
        ])
      );
    }
  }
  node.replaceChildren(...items);
  node.hidden = items.length === 0;
}

function renderStats(stats) {
  const nodes = [
    el("span", { class: "stat" }, [
      `${i18n.t("stats.similarity")} `,
      el("b", { text: `${(stats.similarity * 100).toFixed(1)}%` }),
    ]),
    el("span", { class: `stat${stats.added ? " add" : ""}` }, [
      el("b", { text: `+${stats.added}` }),
      ` ${i18n.t("stats.added")}`,
    ]),
    el("span", { class: `stat${stats.removed ? " del" : ""}` }, [
      el("b", { text: `−${stats.removed}` }),
      ` ${i18n.t("stats.removed")}`,
    ]),
    el("span", { class: `stat${stats.changed ? " mod" : ""}` }, [
      el("b", { text: `~${stats.changed}` }),
      ` ${i18n.t("stats.changed")}`,
    ]),
  ];
  if (stats.formatting) {
    nodes.push(
      el("span", { class: "stat mod" }, [
        el("b", { text: `*${stats.formatting}` }),
        ` ${i18n.t("stats.formatting")}`,
      ])
    );
  }
  const visualCount = visualRegionCount();
  if (visualCount !== null) {
    nodes.push(
      el("span", { class: `stat${visualCount ? " mod" : ""}` }, [
        el("b", { text: `◇${visualCount}` }),
        ` ${i18n.t("stats.visual")}`,
      ])
    );
  }
  $("#stats").replaceChildren(...nodes);
}

/* Number of visual regions, or null while the pixel comparison has not run
   for every page pair. */
function visualRegionCount() {
  const data = state.comparison;
  if (!data || !bothRenderable(data)) return null;
  const pages = Object.values(state.visual);
  if (pages.length < data.page_map.length) return null;
  return pages.reduce((total, page) => total + page.regions.length, 0);
}

/* ---------- text view ---------- */
const ROW_CLASS = { insert: "add", delete: "del", replace: "mod", equal: "equal" };

/* "section:footnotes" -> translated section name; sheet names as they are. */
function pageName(side, index) {
  const pages = (state.comparison.pages && state.comparison.pages[side]) || [];
  const label = pages[index] && pages[index].label;
  if (label && label.startsWith("section:")) return i18n.t(`section.${label.slice(8)}`);
  if (label) return label;
  return i18n.t("page.label", { n: index + 1 });
}

function renderText() {
  const data = state.comparison;
  const container = $("#text-view");
  container.replaceChildren();

  container.append(
    el("div", { class: "pane-heads" }, [
      el("div", { text: `A — ${data.left.name}` }),
      el("div", { text: `B — ${data.right.name}` }),
    ])
  );

  const rows = el("div", { class: "rows" });
  if (!data.rows.length) {
    const scanned = ["left", "right"].some((side) =>
      (data[side].warnings || []).some((w) => w.code === "ocr_unavailable" || w.code === "no_text_layer")
    );
    rows.append(
      el("div", { class: "empty-state" }, [
        i18n.t("empty.noText"),
        " ",
        scanned ? i18n.t("empty.ocrHint") : "",
        bothRenderable(data) ? ` ${i18n.t("empty.visualHint")}` : "",
      ])
    );
  }
  const lastPage = { left: -1, right: -1 };
  data.rows.forEach((row, index) => {
    if (row.hidden_before) {
      rows.append(
        el("div", { class: "gap", text: `⋯ ${i18n.t("gap.hidden", { n: row.hidden_before })} ⋯` })
      );
    }
    if (!row.left && !row.right) return;
    const kind = ROW_CLASS[row.kind] + (row.format_changes ? " fmt" : "");
    const node = el("div", { class: `row ${kind}`, "data-row": String(index) }, [
      buildCell(row, "left", lastPage.left),
      buildCell(row, "right", lastPage.right),
    ]);
    rows.append(node);
    if (row.left) lastPage.left = row.left.page;
    if (row.right) lastPage.right = row.right.page;
  });
  container.append(rows);
}

function appendSegments(target, segments) {
  for (const segment of segments) {
    if (segment.kind === "equal") target.append(document.createTextNode(segment.text));
    else
      target.append(
        el("span", {
          class: segment.kind === "delete" ? "seg-del" : "seg-ins",
          text: segment.text,
        })
      );
  }
}

/* Table rows: one box per cell; changed cells carry the inline diff. */
function buildCells(row, side, line) {
  const wrap = el("span", { class: "text cells" });
  if (row.cells) {
    for (const cell of row.cells) {
      const value = cell[side];
      if (value === null || value === undefined) continue;
      const column = cell[`${side}_column`];
      const changed = cell.kind !== "equal";
      const node = el("span", {
        class: `tcell${changed ? ` ${ROW_CLASS[cell.kind]}` : ""}`,
        title: column || null,
      });
      const inline = cell[`${side}_inline`];
      if (inline) appendSegments(node, inline);
      else if (changed) node.append(el("span", { class: side === "left" ? "seg-del" : "seg-ins", text: value }));
      else node.textContent = value;
      if (!value) node.classList.add("empty");
      wrap.append(node);
    }
    return wrap;
  }
  const columns = (line.style && line.style.columns) || [];
  line.cells.forEach((value, index) => {
    wrap.append(
      el("span", { class: `tcell${value ? "" : " empty"}`, title: columns[index] || null, text: value })
    );
  });
  return wrap;
}

function buildCell(row, side, previousPage = -1) {
  const line = row[side];
  const inline = row[`${side}_inline`];
  if (!line) return el("div", { class: "cell" });

  let text;
  if (line.cells) {
    text = buildCells(row, side, line);
  } else {
    text = el("span", { class: "text" });
    const style = line.style || {};
    if (style.list) text.append(el("span", { class: "list-label", text: `${style.list} ` }));
    if (style.heading !== undefined && style.heading !== null) text.classList.add("heading");
    if (inline && inline.length) appendSegments(text, inline);
    else text.append(document.createTextNode(line.text));
  }
  if (row.format_changes && side === "right") {
    const names = row.format_changes.map((name) => i18n.t(`format.${name}`)).join(", ");
    text.append(el("span", { class: "fmt-note", text: ` ${i18n.t("format.changed", { changes: names })}` }));
  }
  return el("div", { class: "cell" }, [
    el("span", { class: "gutter", text: line.label || String(line.number) }),
    el("span", {
      class: "page-tag",
      text: line.page === previousPage ? "" : pageName(side, line.page),
    }),
    text,
  ]);
}

/* ---------- page view ---------- */
function renderPages() {
  const data = state.comparison;
  const container = $("#page-view");
  container.replaceChildren();
  data.page_map.forEach((pair, pairIndex) => {
    container.append(
      el("div", { class: "page-row", "data-pair": String(pairIndex) }, [
        buildPageCard("left", pair.left, pairIndex),
        buildPageCard("right", pair.right, pairIndex),
      ])
    );
  });
  if (showVisual()) drawVisualRegions();
}

function pageImage(side, index, name) {
  return el("img", {
    src: `/api/compare/${state.comparison.id}/page/${side}/${index}.png?dpi=120`,
    alt: `${name} ${pageName(side, index)}`,
    loading: "lazy",
  });
}

function percentBox(box, size) {
  const width = Math.max(box.x1 - box.x0, 1);
  const height = Math.max(box.bottom - box.top, 1);
  return (
    `left:${(box.x0 / size.width) * 100}%;` +
    `top:${(box.top / size.height) * 100}%;` +
    `width:${(width / size.width) * 100}%;` +
    `height:${(height / size.height) * 100}%`
  );
}

function pageSize(side, index) {
  const page = state.comparison.pages[side][index];
  return page && page.width ? page : { width: 595, height: 842 };
}

function buildPageCard(side, index, pairIndex) {
  const data = state.comparison;
  const name = side === "left" ? data.left.name : data.right.name;
  const renderable = side === "left" ? data.renderable.left : data.renderable.right;

  const card = el("div", { class: "page-card" }, [
    el("div", { class: "page-label" }, [
      el("span", { text: `${side === "left" ? "A" : "B"} — ${name}` }),
      el("span", { text: index === null ? i18n.t("page.none") : pageName(side, index) }),
    ]),
  ]);

  if (index === null || !renderable) {
    card.append(el("div", { class: "page-canvas missing", text: i18n.t("page.missing") }));
    return card;
  }

  const size = pageSize(side, index);
  const canvas = el("div", { class: "page-canvas", "data-side": side, "data-pair": String(pairIndex) });
  canvas.append(pageImage(side, index, name));

  const rects = (data.rects[side] && data.rects[side][String(index)]) || [];
  for (const rect of rects) {
    // Line boxes of paired rows are a faint hint; the changed words carry
    // the colour. Whole inserted/removed lines are coloured as a whole.
    const faint = rect.level === "line" && (rect.kind === "replace" || rect.kind === "format");
    const node = el("button", {
      type: "button",
      class: `rect ${rect.kind}${faint ? " faint" : ""}${rect.level === "word" ? " word" : ""}`,
      title: `${i18n.t(`kind.${rect.kind}`)}: ${rect.text}`,
      "aria-label": `${i18n.t(`kind.${rect.kind}`)}: ${rect.text}`,
      style: percentBox(rect, size),
    });
    node.addEventListener("click", () => jumpToRow(rect.row));
    canvas.append(node);
  }

  card.append(canvas);
  return card;
}

/* From a box on the page to its line in the text view. */
function jumpToRow(rowIndex) {
  setMode("text");
  const node = document.querySelector(`#text-view .row[data-row="${rowIndex}"]`);
  if (!node) return;
  const index = state.changes.indexOf(node);
  if (index >= 0) setCurrentChange(index);
  else node.scrollIntoView({ block: "center" });
}

/* ---------- visual comparison ---------- */
function showVisual() {
  return $("#show-visual").checked && state.comparison && bothRenderable(state.comparison);
}

async function loadVisual() {
  const data = state.comparison;
  if (!data || !bothRenderable(data)) return;
  if (Object.keys(state.visual).length >= data.page_map.length) return;
  if (state.visualLoading) return state.visualLoading;
  setBusy(i18n.t("visual.loading"));
  state.visualLoading = fetch(`/api/compare/${data.id}/visual`)
    .then(async (response) => {
      if (!response.ok) throw new Error(await readError(response));
      const payload = await response.json();
      if (state.comparison !== data) return;
      for (const page of payload.pages) state.visual[page.pair] = page;
      renderStats(data.stats);
    })
    .catch((error) => toast(error.message || i18n.t("error.generic")))
    .finally(() => {
      state.visualLoading = null;
      setBusy(null);
    });
  return state.visualLoading;
}

function regionNodes(page, side, size) {
  return page.regions.map((region) =>
    el("div", {
      class: `vregion ${region.kind}`,
      title: i18n.t(`kind.${region.kind}`),
      style: percentBox(region, size),
    })
  );
}

async function drawVisualRegions() {
  for (const node of $$("#page-view .vregion")) node.remove();
  if (!showVisual()) return;
  await loadVisual();
  if (!showVisual()) return;
  for (const canvas of $$("#page-view .page-canvas[data-pair]")) {
    const pairIndex = Number(canvas.dataset.pair);
    const page = state.visual[pairIndex];
    const pair = state.comparison.page_map[pairIndex];
    if (!page || pair.left === null || pair.right === null) continue;
    const side = canvas.dataset.side;
    // Regions are in left-page units; the right page is registered onto it.
    const size = pageSize("left", pair.left);
    canvas.append(...regionNodes(page, side, size));
  }
  collectChanges();
}

/* ---------- overlay view ---------- */
async function renderOverlay() {
  const data = state.comparison;
  const container = $("#overlay-view");
  if (container.childElementCount) return;
  container.append(el("p", { class: "note", text: i18n.t("visual.loading") }));
  await loadVisual();
  if (state.comparison !== data) return;
  container.replaceChildren(
    el("p", { class: "note legend" }, [
      el("span", { class: "swatch del" }), ` ${i18n.t("overlay.removed")}  `,
      el("span", { class: "swatch add" }), ` ${i18n.t("overlay.added")}  `,
      el("span", { class: "swatch same" }), ` ${i18n.t("overlay.same")}`,
    ])
  );
  data.page_map.forEach((pair, pairIndex) => {
    const page = state.visual[pairIndex];
    const label = `A ${pair.left === null ? "—" : pageName("left", pair.left)} ↔ B ${
      pair.right === null ? "—" : pageName("right", pair.right)
    }`;
    const count = page ? page.regions.length : 0;
    const summary = page && count
      ? i18n.t("overlay.regions", { n: count, pct: (page.changed_ratio * 100).toFixed(1) })
      : i18n.t("overlay.identical");
    const card = el("div", { class: "page-card overlay-card", "data-pair": String(pairIndex) }, [
      el("div", { class: "page-label" }, [el("span", { text: label }), el("span", { text: summary })]),
    ]);
    if (pair.left === null || pair.right === null) {
      card.append(
        el("div", {
          class: "page-canvas missing",
          text: i18n.t(pair.left === null ? "overlay.onlyRight" : "overlay.onlyLeft"),
        })
      );
    } else {
      const canvas = el("div", { class: "page-canvas" }, [
        el("img", {
          src: `/api/compare/${data.id}/overlay/${pairIndex}.png`,
          alt: label,
          loading: "lazy",
        }),
      ]);
      if (page) canvas.append(...regionNodes(page, "left", pageSize("left", pair.left)));
      card.append(canvas);
    }
    if (count || pair.left === null || pair.right === null) card.classList.add("changed");
    container.append(card);
  });
  collectChanges();
}

/* ---------- busy note and toast ---------- */
function setBusy(message) {
  let node = $("#busy");
  if (!message) {
    if (node) node.remove();
    return;
  }
  if (!node) {
    node = el("div", { id: "busy", class: "toast", role: "status" });
    document.body.append(node);
  }
  node.replaceChildren(el("span", { class: "spinner" }), ` ${message}`);
}

function toast(message) {
  const node = el("div", { class: "toast", role: "status", text: message });
  document.body.append(node);
  setTimeout(() => node.remove(), 4000);
}

/* ---------- change navigation (n / p, F3 / Shift+F3) ---------- */
function collectChanges() {
  if (!state.comparison) {
    state.changes = [];
    state.changeIndex = -1;
    updateChangeNav();
    return;
  }
  if (state.mode === "pages") {
    state.changes = $$("#page-view .page-row").filter((row) =>
      row.querySelector(".rect, .vregion")
    );
  } else if (state.mode === "overlay") {
    state.changes = $$("#overlay-view .overlay-card.changed");
  } else {
    state.changes = $$(
      "#text-view .row.add, #text-view .row.del, #text-view .row.mod, #text-view .row.fmt"
    ).filter((row) => row.offsetParent !== null);
  }
  state.changeIndex = -1;
  updateChangeNav();
}

function updateChangeNav() {
  const nav = $("#change-nav");
  if (!nav) return;
  nav.hidden = state.changes.length === 0;
  const current = Math.max(state.changeIndex + 1, 0);
  $("#change-count").textContent = i18n.t("nav.position", {
    current,
    total: state.changes.length,
  });
}

function setCurrentChange(index) {
  if (!state.changes.length) return;
  state.changes.forEach((node) => node.classList.remove("current"));
  const node = state.changes[index];
  state.changeIndex = index;
  if (!node) return;
  node.classList.add("current");
  node.scrollIntoView({
    block: "center",
    behavior: reducedMotion() ? "auto" : "smooth",
  });
  updateChangeNav();
}

function gotoChange(delta) {
  if (!state.changes.length) return;
  let index = state.changeIndex + delta;
  if (index < 0) index = state.changes.length - 1;
  if (index >= state.changes.length) index = 0;
  setCurrentChange(index);
}

/* ---------- view switches ---------- */
function setMode(mode) {
  state.mode = mode;
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
  $("#text-view").hidden = mode !== "text";
  $("#page-view").hidden = mode !== "pages";
  $("#overlay-view").hidden = mode !== "overlay";
  $("#only-diff-wrap").hidden = mode !== "text";
  $("#visual-wrap").hidden = mode !== "pages" || !bothRenderable(state.comparison);
  $("#zoom-wrap").hidden = mode === "text";
  applyZoom();
  collectChanges();
  if (mode === "overlay") renderOverlay();
  if (mode === "pages" && showVisual()) drawVisualRegions();

  if (state.comparison && state.comparison.id) {
    history.replaceState(null, "", viewUrl(state.comparison));
  }
}

function applyZoom() {
  for (const view of [$("#page-view"), $("#overlay-view")]) {
    view.style.maxWidth = `${(view.id === "overlay-view" ? 900 : 1500) * state.zoom}px`;
  }
  $("#zoom-label").textContent = `%${Math.round(state.zoom * 100)}`;
}

function showUploadView() {
  state.comparison = null;
  state.visual = {};
  state.changes = [];
  state.changeIndex = -1;
  history.replaceState(null, "", location.pathname);
  $("#result-view").hidden = true;
  $("#upload-view").hidden = false;
  $("#view-tabs").hidden = true;
  $("#only-diff-wrap").hidden = true;
  $("#visual-wrap").hidden = true;
  $("#zoom-wrap").hidden = true;
  $("#change-nav").hidden = true;
  $("#stats").replaceChildren();
  $("#overlay-view").replaceChildren();
  for (const node of $$("[data-result-only]")) node.hidden = true;
  closeMenus();
  hideError();
  updateCompareButton();
  window.scrollTo({ top: 0 });
}

function reset() {
  state.files = { left: null, right: null };
  desktop.paths = { left: null, right: null };
  for (const node of $$(".drop")) {
    node.classList.remove("filled");
    const chip = node.querySelector(".file-chip");
    chip.hidden = true;
    chip.textContent = "";
    node.querySelector("input[type=file]").value = "";
  }
  $("#only-diff").checked = false;
  document.body.classList.remove("only-diff");
  showUploadView();
  updateCompareButton();
}

/* ---------- capabilities (OCR engine) ---------- */
async function loadCapabilities() {
  try {
    const response = await fetch("/api/capabilities");
    if (!response.ok) return;
    state.capabilities = await response.json();
  } catch (_) {
    return;
  }
  renderOcrNote();
}

function renderOcrNote() {
  const node = $("#ocr-note");
  const caps = state.capabilities;
  if (!node || !caps) return;
  node.hidden = Boolean(caps.ocr && caps.ocr.available);
  node.textContent = i18n.t("opt.ocrMissing");
}

/* ---------- update check ---------- */
async function checkUpdates() {
  const status = $("#updates-status");
  const link = $("#updates-link");
  const button = $("#updates-check");
  button.disabled = true;
  link.hidden = true;
  status.textContent = i18n.t("updates.checking");
  try {
    const response = await fetch("/api/updates");
    if (!response.ok) throw new Error(await readError(response));
    const info = await response.json();
    if (info.status === "update") {
      status.textContent = i18n.t("updates.available", { version: info.latest, current: info.current });
      link.href = info.url;
      link.hidden = false;
    } else if (info.status === "latest") {
      status.textContent = i18n.t("updates.latest", { version: info.current });
    } else if (info.status === "no_releases") {
      status.textContent = i18n.t("updates.noReleases");
      link.href = info.url;
      link.hidden = false;
    } else {
      status.textContent = i18n.t("updates.failed", { message: info.message || "" });
    }
  } catch (error) {
    status.textContent = i18n.t("updates.failed", { message: error.message || "" });
  } finally {
    button.disabled = false;
  }
}

/* ---------- deep link: /?id=<comparison>&view=pages ---------- */
async function restoreFromUrl() {
  const params = new URLSearchParams(location.search);
  const id = params.get("id");
  if (!id) return;
  try {
    const response = await fetch(`/api/compare/${id}`);
    if (!response.ok) return;
    setComparison(await response.json());
    const view = params.get("view");
    state.mode = view === "pages" || view === "overlay" ? view : "text";
    renderResult();
  } catch (_) {
    /* stale link: fall back to the upload view */
  }
}

/* ---------- desktop shell bridge ---------- */
function initDesktop() {
  if (!window.pywebview || !window.pywebview.api) return;
  desktop.available = true;
  state.isDesktop = true;
  document.body.classList.add("desktop");
  renderVersion();

  const api = window.pywebview.api;
  api
    .startup_selection()
    .then((selection) => {
      if (!selection) return;
      for (const side of ["left", "right"]) {
        if (!selection[side]) continue;
        desktop.paths[side] = selection[side];
        showPath(side, selection[side]);
      }
      updateCompareButton();
      if (desktop.paths.left && desktop.paths.right) runComparison();
    })
    .catch(() => {});
}

/* A second process (context menu) hands files to this window. */
window.diffanydocReceive = function (payload) {
  if (!payload || !payload.path) return;
  const side = payload.slot;
  if (side !== "left" && side !== "right") return;
  if (!$("#result-view").hidden) showUploadView();
  desktop.paths[side] = payload.path;
  showPath(side, payload.path);
  updateCompareButton();
  if (desktop.paths.left && desktop.paths.right) runComparison();
};

window.addEventListener("pywebviewready", initDesktop);

/* In the desktop shell, reports open in the real browser, not the webview. */
$("#export").addEventListener("click", (event) => {
  closeMenus();
  if (!desktop.available) return;
  event.preventDefault();
  const href = $("#export").getAttribute("href");
  if (href) window.pywebview.api.open_external(new URL(href, location.origin).href);
});

/* ---------- wiring ---------- */
setupDropZones();
setupMenus();
setupDialogs();
loadTheme();
loadCapabilities();
$("#compare").addEventListener("click", runComparison);
$("#restart").addEventListener("click", reset);

$$(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    if (!tab.disabled) setMode(tab.dataset.mode);
  })
);

$("#show-visual").addEventListener("change", () => {
  drawVisualRegions();
});

$("#only-diff").addEventListener("change", (event) => {
  document.body.classList.toggle("only-diff", event.target.checked);
  collectChanges();
});

$("#zoom-in").addEventListener("click", () => {
  state.zoom = Math.min(2, Math.round((state.zoom + 0.1) * 10) / 10);
  applyZoom();
});
$("#zoom-out").addEventListener("click", () => {
  state.zoom = Math.max(0.5, Math.round((state.zoom - 0.1) * 10) / 10);
  applyZoom();
});

$("#prev-change").addEventListener("click", () => gotoChange(-1));
$("#next-change").addEventListener("click", () => gotoChange(1));

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    if ($("#upload-view").hidden === false) runComparison();
    return;
  }

  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const tag = (event.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable) {
    return;
  }
  if ($("#result-view").hidden) return;

  if (event.key === "n" || (event.key === "F3" && !event.shiftKey)) {
    event.preventDefault();
    gotoChange(1);
  } else if (event.key === "p" || (event.key === "F3" && event.shiftKey)) {
    event.preventDefault();
    gotoChange(-1);
  }
});

async function init() {
  await loadLanguage(preferredLanguage());
  await restoreFromUrl();
  if (window.pywebview && window.pywebview.api) initDesktop();
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    state.version = health.version;
    renderVersion();
  } catch (_) {
    /* the version note is cosmetic */
  }
}

init();
