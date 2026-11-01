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
  visual: null,
  ocr: null,
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
    const ocr = $("#opt-ocr").checked;
    if (desktop.available && desktop.paths.left && desktop.paths.right) {
      response = await fetch("/api/compare-paths", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          left: desktop.paths.left,
          right: desktop.paths.right,
          case_sensitive: caseSensitive,
          collapse_whitespace: collapseWhitespace,
          fold_equal: false,
          context: 3,
          ocr,
          ocr_language: "eng",
        }),
      });
    } else {
      const form = new FormData();
      form.append("left", state.files.left);
      form.append("right", state.files.right);
      form.append("case_sensitive", String(caseSensitive));
      form.append("collapse_whitespace", String(collapseWhitespace));
      form.append("fold_equal", "false");
      form.append("context", "3");
      form.append("ocr", String(ocr));
      form.append("ocr_language", "eng");
      response = await fetch("/api/compare", { method: "POST", body: form });
    }
    if (!response.ok) throw new Error(await readError(response));
    state.comparison = await response.json();
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
function renderResult() {
  const data = state.comparison;
  $("#upload-view").hidden = true;
  $("#result-view").hidden = false;
  $("#view-tabs").hidden = false;

  for (const node of $$("[data-result-only]")) node.hidden = false;

  if (data.id) {
    const view = state.mode === "pages" ? "&view=pages" : "";
    const lang = `&lang=${i18n.lang}`;
    history.replaceState(null, "", `${location.pathname}?id=${data.id}${view}${lang}`);
  }

  $("#name-left").textContent = data.left.name;
  $("#name-right").textContent = data.right.name;
  $("#meta-left").textContent = `${data.left.kind} · ${i18n.t("meta.pages", { n: data.left.pages })}`;
  $("#meta-right").textContent = `${data.right.kind} · ${i18n.t("meta.pages", { n: data.right.pages })}`;

  state.visual = data.visual && data.visual.available ? data.visual : null;
  state.ocr = data.ocr && data.ocr.available ? data.ocr : null;
  renderStats(data.stats);

  const canRender = data.renderable.left || data.renderable.right;
  $("#tab-pages").disabled = !canRender;
  if (!canRender && state.mode === "pages") state.mode = "text";

  $("#visual-wrap").hidden = !state.visual;
  $("#opt-visual").checked = !document.body.classList.contains("visual-off");

  $("#export").href = `/api/compare/${data.id}/report?lang=${i18n.lang}`;

  renderText();
  renderPages();
  setMode(canRender ? state.mode : "text");
  window.scrollTo({ top: 0 });
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
  if (state.visual && state.visual.stats.compared) {
    nodes.push(
      el("span", { class: "stat" }, [
        `${i18n.t("stats.visual")} `,
        el("b", { text: `${(state.visual.stats.similarity * 100).toFixed(1)}%` }),
      ])
    );
  }
  if (state.ocr && state.ocr.pages) {
    nodes.push(
      el("span", { class: "stat" }, [
        `${i18n.t("stats.ocr")} `,
        el("b", { text: String(state.ocr.pages) }),
      ])
    );
  }
  $("#stats").replaceChildren(...nodes);
}

/* ---------- text view ---------- */
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
    rows.append(
      el("div", { class: "empty-state" }, [
        i18n.t("empty.noText"),
        " ",
        i18n.t("empty.ocrHint"),
      ])
    );
  }
  const lastPage = { left: -1, right: -1 };
  for (const row of data.rows) {
    if (row.hidden_before) {
      rows.append(
        el("div", { class: "gap", text: `⋯ ${i18n.t("gap.hidden", { n: row.hidden_before })} ⋯` })
      );
    }
    if (!row.left && !row.right) continue;
    rows.append(
      el(
        "div",
        {
          class: `row ${
            row.kind === "insert"
              ? "add"
              : row.kind === "delete"
                ? "del"
                : row.kind === "replace"
                  ? "mod"
                  : "equal"
          }`,
        },
        [
          buildCell(row.left, row.left_inline, lastPage.left),
          buildCell(row.right, row.right_inline, lastPage.right),
        ]
      )
    );
    if (row.left) lastPage.left = row.left.page;
    if (row.right) lastPage.right = row.right.page;
  }
  container.append(rows);
}

function buildCell(line, inline, previousPage = -1) {
  if (!line) return el("div", { class: "cell" });
  const text = el("span", { class: "text" });
  if (inline && inline.length) {
    for (const segment of inline) {
      if (segment.kind === "equal") text.append(document.createTextNode(segment.text));
      else
        text.append(
          el("span", {
            class: segment.kind === "delete" ? "seg-del" : "seg-ins",
            text: segment.text,
          })
        );
    }
  } else {
    text.textContent = line.text;
  }
  return el("div", { class: "cell" }, [
    el("span", { class: "gutter", text: String(line.number) }),
    el("span", {
      class: "page-tag",
      text: line.page === previousPage ? "" : i18n.t("page.label", { n: line.page + 1 }),
    }),
    text,
  ]);
}

/* ---------- page view ---------- */
function renderPages() {
  const data = state.comparison;
  const container = $("#page-view");
  container.replaceChildren();

  const visualPages = { left: {}, right: {} };
  if (state.visual) {
    for (const page of state.visual.pages) {
      visualPages.left[page.left] = page;
      visualPages.right[page.right] = page;
    }
    if (state.visual.stats.compared) container.append(buildVisualBar(state.visual));
  }

  for (const pair of data.page_map) {
    container.append(
      el("div", { class: "page-row" }, [
        buildPageCard("left", pair.left, visualPages.left[pair.left]),
        buildPageCard("right", pair.right, visualPages.right[pair.right]),
      ])
    );
  }
}

function buildVisualBar(visual) {
  const stats = visual.stats;
  const parts = [
    i18n.t("visual.summary", {
      percent: (stats.similarity * 100).toFixed(1),
      changed: stats.changed_pages,
      pages: stats.compared,
      regions: stats.regions,
    }),
  ];
  if (stats.truncated) parts.push(i18n.t("visual.truncated"));
  return el("div", { class: "visual-bar" }, [
    el("span", { class: "visual-dot", "aria-hidden": "true" }),
    el("span", { text: parts.join(" ") }),
  ]);
}

function addRect(canvas, box, kind, title, pageWidth, pageHeight) {
  const [x0, top, x1, bottom] = box;
  const width = Math.max(x1 - x0, 0.5);
  const height = Math.max(bottom - top, 0.5);
  canvas.append(
    el("div", {
      class: `rect ${kind}`,
      title,
      style:
        `left:${(x0 / pageWidth) * 100}%;` +
        `top:${(top / pageHeight) * 100}%;` +
        `width:${(width / pageWidth) * 100}%;` +
        `height:${(height / pageHeight) * 100}%`,
    })
  );
}

function buildPageCard(side, index, visualPage) {
  const data = state.comparison;
  const name = side === "left" ? data.left.name : data.right.name;
  const renderable = side === "left" ? data.renderable.left : data.renderable.right;

  const card = el("div", { class: "page-card" }, [
    el("div", { class: "page-label" }, [
      el("span", { text: `${side === "left" ? "A" : "B"} — ${name}` }),
      el("span", { text: index === null ? i18n.t("page.none") : i18n.t("page.label", { n: index + 1 }) }),
    ]),
  ]);

  if (index === null || !renderable) {
    card.append(el("div", { class: "page-canvas missing", text: i18n.t("page.missing") }));
    return card;
  }

  const size = data.pages[side][index] || { width: 595, height: 842 };
  const canvas = el("div", { class: "page-canvas" });
  canvas.append(
    el("img", {
      src: `/api/compare/${data.id}/page/${side}/${index}.png?dpi=120`,
      alt: `${name} ${i18n.t("page.label", { n: index + 1 })}`,
      loading: "lazy",
    })
  );

  const rects = (data.rects[side] && data.rects[side][String(index)]) || [];
  for (const rect of rects) {
    addRect(
      canvas,
      [rect.x0, rect.top, rect.x1, rect.bottom],
      rect.kind === "insert" ? "insert" : rect.kind === "delete" ? "delete" : "replace",
      `${rect.kind}: ${rect.text}`,
      size.width,
      size.height
    );
  }

  const visualBoxes =
    visualPage && side === "left"
      ? visualPage.left_regions
      : visualPage
        ? visualPage.right_regions
        : [];
  for (const box of visualBoxes || []) {
    addRect(canvas, box, "visual", i18n.t("visual.region"), size.width, size.height);
  }

  card.append(canvas);
  return card;
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
      Array.from(row.querySelectorAll(".rect")).some((rect) => rect.offsetParent !== null)
    );
  } else {
    state.changes = $$("#text-view .row.add, #text-view .row.del, #text-view .row.mod").filter(
      (row) => row.offsetParent !== null
    );
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
  $("#only-diff-wrap").hidden = mode !== "text";
  $("#zoom-wrap").hidden = mode !== "pages";
  applyZoom();
  collectChanges();

  if (state.comparison && state.comparison.id) {
    const view = mode === "pages" ? "&view=pages" : "";
    history.replaceState(
      null,
      "",
      `${location.pathname}?id=${state.comparison.id}${view}&lang=${i18n.lang}`
    );
  }
}

function applyZoom() {
  $("#page-view").style.maxWidth = `${1500 * state.zoom}px`;
  $("#zoom-label").textContent = `%${Math.round(state.zoom * 100)}`;
}

function showUploadView() {
  state.comparison = null;
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
  state.visual = null;
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
  $("#opt-visual").checked = true;
  document.body.classList.remove("visual-off");
  $("#opt-ocr").checked = false;
  showUploadView();
  updateCompareButton();
}

/* ---------- deep link: /?id=<comparison>&view=pages ---------- */
async function restoreFromUrl() {
  const params = new URLSearchParams(location.search);
  const id = params.get("id");
  if (!id) return;
  try {
    const response = await fetch(`/api/compare/${id}`);
    if (!response.ok) return;
    state.comparison = await response.json();
    state.mode = params.get("view") === "pages" ? "pages" : "text";
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
$("#compare").addEventListener("click", runComparison);
$("#restart").addEventListener("click", reset);

$$(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    if (!tab.disabled) setMode(tab.dataset.mode);
  })
);

$("#only-diff").addEventListener("change", (event) => {
  document.body.classList.toggle("only-diff", event.target.checked);
  collectChanges();
});

$("#opt-visual").addEventListener("change", (event) => {
  document.body.classList.toggle("visual-off", !event.target.checked);
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
