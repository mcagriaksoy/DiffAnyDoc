"use strict";

const state = {
  files: { left: null, right: null },
  comparison: null,
  mode: "text",
  zoom: "width", // number, "width" or "page"
  zoomValue: 1, // resolved scale
  version: "",
  isDesktop: false,
  changes: [],
  changeIndex: -1,
  comparing: false,
  visual: null,
  ocr: null,
  annotating: false,
  annotations: [],
  nextAnnotationId: 1,
  preloadedHashes: { left: "", right: "" },
  tabs: [
    {
      id: "tab-1",
      files: { left: null, right: null },
      paths: { left: null, right: null },
      comparison: null,
      mode: "text",
      zoom: "width",
      annotations: [],
    },
  ],
  activeTabId: "tab-1",
  nextTabSeq: 2,
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
  renderSessionTabs();

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

/* Inline Markdown: **bold** and `code` only. */
function markdownInline(text) {
  const out = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) out.push(text.slice(last, match.index));
    out.push(
      match[1] !== undefined
        ? el("strong", { text: match[1] })
        : el("code", { text: match[2] })
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/* Release notes are remote text: build DOM nodes, never innerHTML. */
function renderMarkdown(source) {
  const blocks = [];
  let list = null;
  let para = [];
  const flush = () => {
    if (para.length) blocks.push(el("p", {}, markdownInline(para.join(" "))));
    para = [];
  };
  for (const raw of String(source || "").split(/\r?\n/)) {
    const line = raw.trim();
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    const item = /^[-*+]\s+(.*)$/.exec(line);
    if (!item) list = null;
    if (!line) {
      flush();
    } else if (heading) {
      flush();
      blocks.push(el("h3", {}, markdownInline(heading[1])));
    } else if (item) {
      flush();
      if (!list) {
        list = el("ul");
        blocks.push(list);
      }
      list.append(el("li", {}, markdownInline(item[1])));
    } else {
      para.push(line);
    }
  }
  flush();
  return blocks;
}

function openExternal(event, href) {
  if (!desktop.available || !href) return;
  event.preventDefault();
  window.pywebview.api.open_external(new URL(href, location.origin).href);
}

let updatesBusy = false;

async function checkUpdates() {
  if (updatesBusy) return;
  updatesBusy = true;
  const status = $("#updates-status");
  const notes = $("#updates-notes");
  const open = $("#updates-open");
  const button = $("#updates-check");
  status.className = "updates-status";
  status.textContent = i18n.t("updates.checking");
  notes.hidden = true;
  open.hidden = true;
  button.disabled = true;
  try {
    const response = await fetch("/api/updates");
    if (!response.ok) throw new Error(await readError(response));
    const info = await response.json();
    if (info.status === "update") {
      status.textContent = i18n.t("updates.available", {
        version: `v${info.latest}`,
        current: `v${info.current}`,
      });
      const blocks = renderMarkdown(info.notes);
      notes.replaceChildren(...blocks);
      notes.hidden = !blocks.length;
      open.href = info.url;
      open.hidden = false;
    } else if (info.status === "latest") {
      status.classList.add("ok");
      status.replaceChildren(
        el("span", { class: "updates-check-icon", "aria-hidden": "true", text: "✓" }),
        i18n.t("updates.latest", { version: `v${info.current}` })
      );
    } else if (info.status === "no_releases") {
      status.textContent = i18n.t("updates.noReleases");
    } else {
      throw new Error(info.message || i18n.t("error.generic"));
    }
  } catch (error) {
    status.classList.add("failed");
    status.textContent = i18n.t("updates.failed", {
      message: error.message || i18n.t("error.generic"),
    });
  } finally {
    button.disabled = false;
    updatesBusy = false;
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

function showHelpPanel(name) {
  for (const tab of $$(".help-tab")) {
    const active = tab.dataset.help === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  for (const panel of $$(".help-panel")) {
    panel.hidden = panel.dataset.helpPanel !== name;
  }
}

function openHelp() {
  closeMenus();
  const dialog = $("#help-dialog");
  if (!dialog.open) dialog.showModal();
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
  $("#help").addEventListener("click", openHelp);
  for (const tab of $$(".help-tab")) {
    tab.addEventListener("click", () => showHelpPanel(tab.dataset.help));
  }
  $("#updates").addEventListener("click", () => {
    closeMenus();
    fillUpdates();
    $("#updates-dialog").showModal();
    checkUpdates();
  });
  $("#updates-check").addEventListener("click", checkUpdates);
  $("#updates-open").addEventListener("click", (event) =>
    openExternal(event, $("#updates-open").getAttribute("href"))
  );
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

    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      document.body.classList.remove("dragging");
      const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
      if (files.length) {
        try {
          input.files = e.dataTransfer.files;
        } catch (_) {
          /* some browsers refuse programmatic assignment; state is what matters */
        }
        assignDroppedFiles(files, side);
        return;
      }
      await handleUriDrop(e.dataTransfer, side);
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

  // Files dropped anywhere else used to open in the webview and lose the
  // comparison. Catch them at document level: two files fill both sides, one
  // file goes to the first empty side (or the zone it was dropped on).
  let dragDepth = 0;
  document.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth += 1;
    document.body.classList.add("dragging");
  });
  document.addEventListener("dragover", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  });
  document.addEventListener("dragleave", (e) => {
    if (dragDepth === 0) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) document.body.classList.remove("dragging");
  });
  // The pointer may leave the window without a final dragleave.
  window.addEventListener("dragend", () => {
    dragDepth = 0;
    document.body.classList.remove("dragging");
  });
  document.addEventListener("drop", async (e) => {
    document.body.classList.remove("dragging");
    dragDepth = 0;
    if (e.defaultPrevented) return; // a drop zone already handled it
    e.preventDefault();
    const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
    if (files.length) {
      assignDroppedFiles(files, null);
      return;
    }
    await handleUriDrop(e.dataTransfer, null);
  });
}

function hasFiles(event) {
  const dt = event.dataTransfer;
  if (!dt) return false;
  if (dt.files && dt.files.length > 0) return true;
  const types = Array.from(dt.types || []);
  return types.some(
    (t) =>
      t === "Files" ||
      t === "text/uri-list" ||
      t === "text/plain" ||
      t.toLowerCase().includes("file") ||
      t.toLowerCase().includes("uri")
  );
}

async function handleUriDrop(dataTransfer, preferredSide) {
  if (!dataTransfer || !desktop.available || !window.pywebview || !window.pywebview.api) {
    return;
  }
  const raw =
    dataTransfer.getData("text/uri-list") ||
    dataTransfer.getData("text/plain") ||
    "";
  if (!raw.trim()) return;
  try {
    const resolved = await window.pywebview.api.resolve_dropped_uris(raw);
    if (!Array.isArray(resolved) || !resolved.length) return;
    if (resolved.length >= 2) {
      desktop.paths.left = resolved[0];
      desktop.paths.right = resolved[1];
      showPath("left", resolved[0]);
      showPath("right", resolved[1]);
    } else {
      const side =
        preferredSide ||
        (!desktop.paths.left && !state.files.left
          ? "left"
          : !desktop.paths.right && !state.files.right
            ? "right"
            : "left");
      desktop.paths[side] = resolved[0];
      showPath(side, resolved[0]);
    }
    if (!$("#result-view").hidden) showUploadView();
    updateCompareButton();
  } catch (_) {
    /* ignore invalid drop payloads */
  }
}

function assignDroppedFiles(files, preferredSide) {
  if (!files.length) return;
  if (files.length >= 2) {
    setFile("left", files[0]);
    setFile("right", files[1]);
  } else {
    const side =
      preferredSide ||
      (!state.files.left ? "left" : !state.files.right ? "right" : "left");
    setFile(side, files[0]);
  }
  if (!$("#result-view").hidden) showUploadView();
  updateCompareButton();
}

function basename(path) {
  return String(path).split(/[\\/]/).pop() || String(path);
}

function showPath(side, path) {
  state.files[side] = null;
  const zone = document.querySelector(`.drop[data-side="${side}"]`);
  if (!zone) return;
  zone.classList.add("filled");
  const chip = zone.querySelector(".file-chip");
  chip.hidden = false;
  chip.textContent = basename(path);
  chip.title = path;
  syncActiveTab();
  preloadSide(side);
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
  desktop.paths[side] = null;
  const zone = document.querySelector(`.drop[data-side="${side}"]`);
  zone.classList.add("filled");
  const chip = zone.querySelector(".file-chip");
  chip.hidden = false;
  chip.textContent = `${file.name} · ${formatBytes(file.size)}`;
  updateCompareButton();
  syncActiveTab();
  preloadSide(side);
}

async function preloadSide(side) {
  const otherSide = side === "left" ? "right" : "left";
  const otherHash = (state.preloadedHashes && state.preloadedHashes[otherSide]) || "";
  const ocrLanguage = i18n.lang === "tr" ? "tur+eng" : "eng";
  try {
    if (desktop.available && desktop.paths[side]) {
      const response = await fetch("/api/preload-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: desktop.paths[side],
          other_sha256: otherHash,
          ocr: true,
          ocr_language: ocrLanguage,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        if (data.sha256) state.preloadedHashes[side] = data.sha256;
      }
      return;
    }
    if (state.files[side]) {
      const form = new FormData();
      form.append("file", state.files[side]);
      form.append("other_sha256", otherHash);
      form.append("ocr", "true");
      form.append("ocr_language", ocrLanguage);
      const response = await fetch("/api/preload", { method: "POST", body: form });
      if (response.ok) {
        const data = await response.json();
        if (data.sha256) state.preloadedHashes[side] = data.sha256;
      }
    }
  } catch (_) {
    /* background preloading is opportunistic */
  }
}

function isReady() {
  if (desktop.available && desktop.paths.left && desktop.paths.right) return true;
  return Boolean(state.files.left && state.files.right);
}

function updateCompareButton() {
  $("#compare").disabled = state.comparing || !isReady();
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
async function comparisonRequest() {
  const caseSensitive = !$("#opt-case").checked;
  const collapseWhitespace = $("#opt-space").checked;
  const formatCheckbox = $("#opt-format");
  const compareFormatting = Boolean(formatCheckbox && formatCheckbox.checked);
  const ocrCheckbox = $("#opt-ocr");
  const ocr = ocrCheckbox ? Boolean(ocrCheckbox.checked) : true;
  const ocrLangSelect = $("#opt-ocr-lang");
  const ocrLanguage = (ocrLangSelect && ocrLangSelect.value) || (i18n.lang === "tr" ? "tur+eng" : "eng");

  if (desktop.available && desktop.paths.left && desktop.paths.right) {
    return fetch("/api/compare-paths", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        left: desktop.paths.left,
        right: desktop.paths.right,
        case_sensitive: caseSensitive,
        collapse_whitespace: collapseWhitespace,
        compare_formatting: compareFormatting,
        fold_equal: false,
        context: 3,
        visual: true,
        ocr,
        ocr_language: ocrLanguage,
      }),
    });
  }

  const form = new FormData();
  form.append("left", state.files.left);
  form.append("right", state.files.right);
  form.append("case_sensitive", String(caseSensitive));
  form.append("collapse_whitespace", String(collapseWhitespace));
  form.append("compare_formatting", String(compareFormatting));
  form.append("fold_equal", "false");
  form.append("context", "3");
  form.append("visual", "true");
  form.append("ocr", String(ocr));
  form.append("ocr_language", ocrLanguage);
  return fetch("/api/compare", { method: "POST", body: form });
}

function canReload() {
  if (desktop.available && desktop.paths.left && desktop.paths.right) return true;
  return Boolean(state.files.left && state.files.right);
}

function setComparing(active) {
  state.comparing = active;
  const button = $("#compare");
  const spinner = button.querySelector(".spinner");
  button.disabled = active || !isReady();
  spinner.hidden = !active;
  const reload = $("#reload");
  if (reload) reload.disabled = active;
}

async function runComparison() {
  if (!isReady() || state.comparing) return;
  hideError();
  setComparing(true);

  try {
    const response = await comparisonRequest();
    if (!response.ok) throw new Error(await readError(response));
    state.comparison = await response.json();
    renderResult();
  } catch (error) {
    showError(error.message || i18n.t("error.generic"));
  } finally {
    setComparing(false);
    updateCompareButton();
  }
}

async function reloadComparison() {
  if (!state.comparison || state.comparing || !canReload()) return;
  const scroll = window.scrollY;
  const mode = state.mode;
  const reload = $("#reload");
  state.comparing = true;
  reload.disabled = true;
  reload.classList.add("busy");

  try {
    const response = await comparisonRequest();
    if (!response.ok) throw new Error(await readError(response));
    state.comparison = await response.json();
    renderResult();
    if (!$("#tab-pages").disabled) setMode(mode);
    window.scrollTo({ top: scroll });
    showToast(i18n.t("reload.done"));
  } catch (error) {
    showToast(error.message || i18n.t("error.generic"), true);
  } finally {
    state.comparing = false;
    reload.disabled = false;
    reload.classList.remove("busy");
    updateCompareButton();
  }
}

/* ---------- copy ---------- */
function buildCopyText(kind) {
  const data = state.comparison;
  if (!data) return "";
  const rows = data.rows || [];

  if (kind === "left" || kind === "right") {
    return rows
      .map((row) => (kind === "left" ? row.left : row.right))
      .filter(Boolean)
      .map((line) => line.text)
      .join("\n");
  }

  if (kind === "both") {
    const lines = [`A: ${data.left.name}`, `B: ${data.right.name}`, ""];
    for (const row of rows) {
      if (!row.left && !row.right) continue;
      lines.push(`${row.left ? row.left.text : ""}\t${row.right ? row.right.text : ""}`);
    }
    return lines.join("\n");
  }

  const out = [`A: ${data.left.name}`, `B: ${data.right.name}`, ""];
  let changed = 0;
  for (const row of rows) {
    if (row.kind === "equal") continue;
    changed += 1;
    if (row.hidden_before) out.push(`... ${row.hidden_before} unchanged lines ...`);
    if (row.kind === "replace" && row.left && row.right) {
      out.push(`~ ${row.left.number} -> ${row.right.number}`);
      out.push(`- ${row.left.text}`);
      out.push(`+ ${row.right.text}`);
    } else if (row.kind === "insert" && row.right) {
      out.push(`+ ${row.right.number}: ${row.right.text}`);
    } else if (row.kind === "delete" && row.left) {
      out.push(`- ${row.left.number}: ${row.left.text}`);
    }
  }
  return changed ? out.join("\n") : "";
}

async function copyText(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) {
    /* fall back to execCommand below */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch (_) {
    copied = false;
  }
  area.remove();
  return copied;
}

async function copyView(kind) {
  closeMenus();
  const text = buildCopyText(kind);
  if (!text) {
    showToast(i18n.t("copy.none"), true);
    return;
  }
  const copied = await copyText(text);
  showToast(copied ? i18n.t("copy.done") : i18n.t("copy.failed"), !copied);
}

async function copyLine(text) {
  const copied = await copyText(text);
  showToast(
    copied ? i18n.t("copy.lineDone") : i18n.t("copy.failed"),
    !copied
  );
}

function recomputeStatsFromRows(data) {
  const rows = data.rows || [];
  let added = 0;
  let removed = 0;
  let changed = 0;
  let leftChars = 0;
  let rightChars = 0;
  let matched = 0;

  for (const row of rows) {
    if (row.left && row.left.text) leftChars += row.left.text.length;
    if (row.right && row.right.text) rightChars += row.right.text.length;
    if (row.kind === "insert") added += 1;
    else if (row.kind === "delete") removed += 1;
    else if (row.kind === "replace") changed += 1;
    else if (row.kind === "equal") {
      const lLen = row.left && row.left.text ? row.left.text.length : 0;
      const rLen = row.right && row.right.text ? row.right.text.length : 0;
      matched += lLen + rLen;
    }
  }
  const total = leftChars + rightChars;
  data.stats = {
    ...data.stats,
    added,
    removed,
    changed,
    similarity: total ? Math.min(matched / total, 1.0) : 1.0,
  };
  data.identical = added === 0 && removed === 0 && changed === 0;
}

function applyRowChangeToSide(row, fromSide) {
  const toSide = fromSide === "left" ? "right" : "left";
  const srcLine = row[fromSide];
  if (!srcLine) return false;
  const dstExisting = row[toSide];
  row[toSide] = {
    text: srcLine.text,
    page: dstExisting ? dstExisting.page : srcLine.page,
    number: dstExisting ? dstExisting.number : srcLine.number,
    bbox: dstExisting ? dstExisting.bbox : srcLine.bbox,
    cells: srcLine.cells ? [...srcLine.cells] : null,
    style: srcLine.style ? { ...srcLine.style } : {},
  };
  if (row[fromSide] && row[fromSide].style) {
    delete row[fromSide].style.style_change;
  }
  if (row[toSide] && row[toSide].style) {
    delete row[toSide].style.style_change;
  }
  row.kind = "equal";
  row.left_inline = null;
  row.right_inline = null;
  return true;
}

async function mergeRowToSide(rowIndex, fromSide) {
  const data = state.comparison;
  if (!data || !Array.isArray(data.rows)) return;
  const row = data.rows[rowIndex];
  if (!row || !row[fromSide]) return;
  const copiedText = row[fromSide].text;
  applyRowChangeToSide(row, fromSide);
  recomputeStatsFromRows(data);
  syncActiveTab();
  const scroll = window.scrollY;
  renderStats(data.stats);
  renderText();
  collectChanges();
  window.scrollTo({ top: scroll });
  await copyText(copiedText);
  showToast(
    i18n.t(
      fromSide === "left" ? "merge.lineToRightDone" : "merge.lineToLeftDone"
    )
  );
}

async function mergeAllToSide(fromSide) {
  closeMenus();
  const data = state.comparison;
  if (!data || !Array.isArray(data.rows)) return;
  const toSide = fromSide === "left" ? "right" : "left";
  const nextRows = [];
  let applied = 0;

  for (const row of data.rows) {
    if (row.kind === "equal") {
      nextRows.push(row);
      continue;
    }
    if (row[fromSide]) {
      applyRowChangeToSide(row, fromSide);
      nextRows.push(row);
      applied += 1;
    } else {
      // Opposite side had an extra line not present in fromSide: remove it on target
      applied += 1;
    }
  }
  if (!applied) {
    showToast(i18n.t("copy.none"), true);
    return;
  }
  data.rows = nextRows;
  recomputeStatsFromRows(data);
  syncActiveTab();
  const scroll = window.scrollY;
  renderStats(data.stats);
  renderText();
  collectChanges();
  window.scrollTo({ top: scroll });
  await copyText(buildCopyText(toSide));
  showToast(
    i18n.t("merge.allDone", {
      side: toSide === "left" ? `A (${data.left.name})` : `B (${data.right.name})`,
    })
  );
}

function downloadSideDocument(side) {
  closeMenus();
  const data = state.comparison;
  if (!data) return;
  const text = buildCopyText(side);
  const sourceName = (data[side] && data[side].name) || `${side}.txt`;
  const dot = sourceName.lastIndexOf(".");
  const stem = dot > 0 ? sourceName.slice(0, dot) : sourceName;
  const ext = dot > 0 ? sourceName.slice(dot).toLowerCase() : ".txt";
  const textExts = [".txt", ".md", ".csv", ".tsv", ".json", ".py", ".js", ".html", ".css", ".xml", ".yaml", ".yml"];
  const outName = `${stem}-merged${textExts.includes(ext) ? ext : ".txt"}`;
  const blob = new Blob([text + (text ? "\n" : "")], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = outName;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
  showToast(i18n.t("merge.downloadDone", { name: outName }));
}

/* ---------- session tabs ---------- */
function activeTab() {
  return state.tabs.find((t) => t.id === state.activeTabId) || state.tabs[0];
}

function syncActiveTab() {
  const tab = activeTab();
  if (!tab) return;
  tab.files = { left: state.files.left, right: state.files.right };
  tab.paths = { left: desktop.paths.left, right: desktop.paths.right };
  tab.comparison = state.comparison;
  tab.mode = state.mode;
  tab.zoom = state.zoom;
  tab.annotations = state.annotations ? [...state.annotations] : [];
  renderSessionTabs();
}

function tabTitle(tab) {
  if (tab.comparison && tab.comparison.left && tab.comparison.right) {
    return `${tab.comparison.left.name} ↔ ${tab.comparison.right.name}`;
  }
  const leftName =
    (tab.files.left && tab.files.left.name) ||
    (tab.paths.left && basename(tab.paths.left)) ||
    "";
  const rightName =
    (tab.files.right && tab.files.right.name) ||
    (tab.paths.right && basename(tab.paths.right)) ||
    "";
  if (leftName && rightName) return `${leftName} ↔ ${rightName}`;
  if (leftName || rightName) return leftName || rightName;
  return i18n.t("app.newComparison");
}

function tabHasContent(tab) {
  return Boolean(
    tab.comparison ||
      tab.files.left ||
      tab.files.right ||
      tab.paths.left ||
      tab.paths.right
  );
}

function renderSessionTabs() {
  const container = $("#session-tabs");
  if (!container) return;
  const addBtn = $("#add-tab");
  container.replaceChildren();
  for (const tab of state.tabs) {
    const labelText = tabTitle(tab);
    const children = [
      el("span", { class: "session-tab-label", text: labelText }),
    ];
    // The last tab can close too once it holds files.
    if (state.tabs.length > 1 || tabHasContent(tab)) {
      const close = (e) => {
        e.stopPropagation();
        e.preventDefault();
        closeSessionTab(tab.id);
      };
      children.push(
        el("span", {
          class: "session-tab-close",
          role: "button",
          tabindex: "0",
          title: i18n.t("tab.close"),
          "aria-label": i18n.t("tab.close"),
          text: "\u00d7",
          onclick: close,
          onkeydown: (e) => {
            if (e.key === "Enter" || e.key === " ") close(e);
          },
        })
      );
    }
    const btn = el(
      "button",
      {
        class: `session-tab${tab.id === state.activeTabId ? " active" : ""}`,
        "data-tab-id": tab.id,
        role: "tab",
        type: "button",
        title: labelText,
        onclick: () => switchSessionTab(tab.id),
      },
      children
    );
    container.append(btn);
  }
  if (addBtn) container.append(addBtn);
}

function restoreDropChipsFromState() {
  for (const side of ["left", "right"]) {
    const zone = document.querySelector(`.drop[data-side="${side}"]`);
    if (!zone) continue;
    const chip = zone.querySelector(".file-chip");
    const input = zone.querySelector("input[type=file]");
    if (desktop.available && desktop.paths[side]) {
      zone.classList.add("filled");
      chip.hidden = false;
      chip.textContent = basename(desktop.paths[side]);
      chip.title = desktop.paths[side];
    } else if (state.files[side]) {
      zone.classList.add("filled");
      chip.hidden = false;
      chip.textContent = `${state.files[side].name} · ${formatBytes(state.files[side].size)}`;
    } else {
      zone.classList.remove("filled");
      chip.hidden = true;
      chip.textContent = "";
      if (input) input.value = "";
    }
  }
}

function switchSessionTab(tabId) {
  syncActiveTab();
  const target = state.tabs.find((t) => t.id === tabId);
  if (!target) return;
  state.activeTabId = target.id;
  state.files = { left: target.files.left, right: target.files.right };
  desktop.paths = { left: target.paths.left, right: target.paths.right };
  state.comparison = target.comparison;
  state.mode = target.mode || "text";
  state.zoom = target.zoom || "width";
  state.annotations = Array.isArray(target.annotations) ? [...target.annotations] : [];
  restoreDropChipsFromState();
  renderSessionTabs();
  if (state.comparison) {
    renderResult();
  } else {
    showUploadView();
  }
}

function createNewSessionTab() {
  closeMenus();
  syncActiveTab();
  const newId = `tab-${state.nextTabSeq++}`;
  state.tabs.push({
    id: newId,
    files: { left: null, right: null },
    paths: { left: null, right: null },
    comparison: null,
    mode: "text",
    zoom: "width",
    annotations: [],
  });
  switchSessionTab(newId);
}

function closeSessionTab(tabId) {
  if (state.tabs.length <= 1) {
    // Last tab: back to a clean home screen.
    state.mode = "text";
    state.zoom = "width";
    reset();
    return;
  }
  const idx = state.tabs.findIndex((t) => t.id === tabId);
  if (idx < 0) return;
  const wasActive = tabId === state.activeTabId;
  state.tabs.splice(idx, 1);
  if (wasActive) {
    const nextTab = state.tabs[Math.max(0, idx - 1)];
    state.activeTabId = nextTab.id;
    state.files = { left: nextTab.files.left, right: nextTab.files.right };
    desktop.paths = { left: nextTab.paths.left, right: nextTab.paths.right };
    state.comparison = nextTab.comparison;
    state.mode = nextTab.mode || "text";
    state.zoom = nextTab.zoom || "width";
    state.annotations = Array.isArray(nextTab.annotations) ? [...nextTab.annotations] : [];
    restoreDropChipsFromState();
    if (state.comparison) renderResult();
    else showUploadView();
  }
  renderSessionTabs();
}

/* ---------- toast ---------- */
let toastTimer = 0;
function showToast(message, isError = false) {
  const node = $("#toast");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.hidden = true;
  }, 2400);
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
  const canXray = Boolean(data.renderable.left && data.renderable.right);
  $("#tab-pages").disabled = !canRender;
  if ($("#tab-xray")) $("#tab-xray").disabled = !canXray;
  if (!canRender && (state.mode === "pages" || state.mode === "xray")) state.mode = "text";
  if (!canXray && state.mode === "xray") state.mode = canRender ? "pages" : "text";

  $("#visual-wrap").hidden = !state.visual;
  $("#opt-visual").checked = !document.body.classList.contains("visual-off");
  $("#reload").hidden = !canReload();

  $("#export").href = `/api/compare/${data.id}/report?lang=${i18n.lang}`;

  syncActiveTab();
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
  if (state.comparison && state.comparison.byte_identical) {
    nodes.push(
      el("span", { class: "stat" }, [
        el("b", { text: i18n.t("stats.byteIdentical") }),
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
  const fragment = document.createDocumentFragment();
  if (!data.rows.length) {
    fragment.append(
      el(
        "div",
        { class: "empty-state" },
        data.byte_identical
          ? [i18n.t("empty.byteIdentical")]
          : [i18n.t("empty.noText"), " ", i18n.t("empty.ocrHint")]
      )
    );
  }
  const lastPage = { left: -1, right: -1 };
  for (let rowIndex = 0; rowIndex < data.rows.length; rowIndex++) {
    const row = data.rows[rowIndex];
    if (row.hidden_before) {
      fragment.append(
        el("div", { class: "gap", text: `⋯ ${i18n.t("gap.hidden", { n: row.hidden_before })} ⋯` })
      );
    }
    if (!row.left && !row.right) continue;
    fragment.append(
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
          buildCell(
            row.left,
            row.left_inline,
            lastPage.left,
            "left",
            row.kind !== "equal",
            rowIndex
          ),
          buildCell(
            row.right,
            row.right_inline,
            lastPage.right,
            "right",
            row.kind !== "equal",
            rowIndex
          ),
        ]
      )
    );
    if (row.left) lastPage.left = row.left.page;
    if (row.right) lastPage.right = row.right.page;
  }
  rows.append(fragment);
  container.append(rows);
}

function buildCell(
  line,
  inline,
  previousPage = -1,
  side = "left",
  copyable = false,
  rowIndex = -1
) {
  if (!line) return el("div", { class: "cell" });
  const text = el("span", { class: "text" });
  if (inline && inline.length) {
    for (const segment of inline) {
      if (segment.kind === "equal") text.append(document.createTextNode(segment.text));
      else
        text.append(
          el("span", {
            class: segment.text.trim() === ""
              ? "seg-minor"
              : segment.kind === "delete"
                ? "seg-del"
                : "seg-ins",
            text: segment.text,
          })
        );
    }
  } else {
    text.textContent = line.text;
  }
  if (line.style && line.style.style_change) {
    text.append(
      el("span", {
        class: "page-tag",
        title: line.style.style_change,
        text: line.style.summary || line.style.style_change,
      })
    );
  }
  const gutter = el("span", { class: "gutter" });
  if (copyable) {
    const label = i18n.t(
      side === "left" ? "copy.lineToRight" : "copy.lineToLeft"
    );
    gutter.append(
      el("button", {
        class: "gutter-copy",
        type: "button",
        title: label,
        "aria-label": label,
        text: side === "left" ? "\u2192" : "\u2190",
        onclick: () => {
          if (rowIndex >= 0) mergeRowToSide(rowIndex, side);
          else copyLine(line.text);
        },
      })
    );
  }
  gutter.append(
    el("span", { class: "gutter-number", text: String(line.number) })
  );
  return el("div", { class: "cell" }, [
    gutter,
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

  if (state.mode === "xray") {
    container.append(
      el("div", { class: "visual-bar" }, [
        el("span", { class: "visual-dot", "aria-hidden": "true" }),
        el("span", { text: i18n.t("xray.hint") }),
      ])
    );
    for (let pairIdx = 0; pairIdx < data.page_map.length; pairIdx++) {
      const pair = data.page_map[pairIdx];
      container.append(
        el("div", { class: "page-row xray-row" }, [
          buildXrayCard(pair, pairIdx, visualPages.left[pair.left]),
        ])
      );
    }
    return;
  }

  for (let pairIdx = 0; pairIdx < data.page_map.length; pairIdx++) {
    const pair = data.page_map[pairIdx];
    container.append(
      el("div", { class: "page-row" }, [
        buildPageCard("left", pair.left, visualPages.left[pair.left], pairIdx),
        buildPageCard("right", pair.right, visualPages.right[pair.right], pairIdx),
      ])
    );
  }
}

function buildXrayCard(pair, pairIdx, visualPage) {
  const data = state.comparison;
  const label = `X-Ray: A (${data.left.name}) ↔ B (${data.right.name})`;
  const pageText =
    pair.left !== null && pair.right !== null
      ? `${i18n.t("page.label", { n: pair.left + 1 })} ↔ ${i18n.t("page.label", { n: pair.right + 1 })}`
      : i18n.t("page.none");

  const card = el("div", { class: "page-card" }, [
    el("div", { class: "page-label" }, [
      el("span", { text: label }),
      el("span", { text: pageText }),
    ]),
  ]);

  if (
    pair.left === null ||
    pair.right === null ||
    !data.renderable.left ||
    !data.renderable.right
  ) {
    card.append(missingCanvas());
    return card;
  }

  const sizeL = data.pages.left[pair.left] || { width: 595, height: 842 };
  const sizeR = data.pages.right[pair.right] || { width: 595, height: 842 };
  const size = {
    width: Math.max(sizeL.width, sizeR.width),
    height: Math.max(sizeL.height, sizeR.height),
  };

  const canvas = el("div", { class: "page-canvas", style: canvasStyle(size) });
  canvas.append(
    pageImage(
      `/api/compare/${data.id}/xray/${pair.left}/${pair.right}.png`,
      `${label} ${pageText}`
    )
  );

  // Also show OCR/text diff boxes and visual boxes so hovering shows the text
  const rectsL = (data.rects.left && data.rects.left[String(pair.left)]) || [];
  const rectsR = (data.rects.right && data.rects.right[String(pair.right)]) || [];
  for (const rect of [...rectsL, ...rectsR]) {
    addRect(
      canvas,
      [rect.x0, rect.top, rect.x1, rect.bottom],
      rect.kind === "insert" ? "insert" : rect.kind === "delete" ? "delete" : "replace",
      `${rect.kind}: ${rect.text}`,
      size.width,
      size.height
    );
  }
  for (const box of (visualPage && visualPage.left_regions) || []) {
    addRect(canvas, box, "visual", i18n.t("visual.region"), size.width, size.height);
  }

  renderManualAnnotations(canvas, pairIdx, "xray");
  attachManualAnnotationDrawing(canvas, pairIdx, "xray");
  card.append(canvas);
  return card;
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

function buildPageCard(side, index, visualPage, pairIdx = 0) {
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
    card.append(missingCanvas());
    return card;
  }

  const size = data.pages[side][index] || { width: 595, height: 842 };
  const canvas = el("div", { class: "page-canvas", style: canvasStyle(size) });
  canvas.append(
    pageImage(
      `/api/compare/${data.id}/page/${side}/${index}.png`,
      `${name} ${i18n.t("page.label", { n: index + 1 })}`
    )
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

  renderManualAnnotations(canvas, pairIdx, side);
  attachManualAnnotationDrawing(canvas, pairIdx, side);
  card.append(canvas);
  return card;
}

function renderManualAnnotations(canvas, pairIdx, side) {
  for (const existing of canvas.querySelectorAll(".rect.manual")) {
    existing.remove();
  }
  const items = (state.annotations || []).filter(
    (ann) => ann.pairIdx === pairIdx && (ann.side === side || ann.side === "both")
  );
  for (const ann of items) {
    const box = el(
      "div",
      {
        class: "rect manual",
        title: ann.note || i18n.t("annotate.defaultNote"),
        style: `left:${ann.x}%;top:${ann.y}%;width:${ann.w}%;height:${ann.h}%`,
      },
      [
        el("span", { class: "rect-label" }, [
          el("span", { text: ann.note || i18n.t("annotate.defaultNote") }),
          el("button", {
            class: "rect-del",
            type: "button",
            title: i18n.t("annotate.deleteHint"),
            text: "\u00d7",
            onclick: (e) => {
              e.stopPropagation();
              removeManualAnnotation(ann.id);
            },
          }),
        ]),
      ]
    );
    canvas.append(box);
  }
}

function removeManualAnnotation(id) {
  state.annotations = (state.annotations || []).filter((a) => a.id !== id);
  syncActiveTab();
  if ($("#annotate-clear")) {
    $("#annotate-clear").hidden = state.annotations.length === 0;
  }
  renderPages();
  collectChanges();
}

function clearManualAnnotations() {
  state.annotations = [];
  syncActiveTab();
  if ($("#annotate-clear")) $("#annotate-clear").hidden = true;
  renderPages();
  collectChanges();
  showToast(i18n.t("annotate.cleared"));
}

function attachManualAnnotationDrawing(canvas, pairIdx, side) {
  let startX = 0;
  let startY = 0;
  let draft = null;

  canvas.addEventListener("mousedown", (e) => {
    if (!state.annotating || e.button !== 0) return;
    if (e.target.closest(".rect-del")) return;
    e.preventDefault();
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    startX = ((e.clientX - bounds.left) / bounds.width) * 100;
    startY = ((e.clientY - bounds.top) / bounds.height) * 100;
    draft = el("div", {
      class: "rect manual",
      style: `left:${startX}%;top:${startY}%;width:0%;height:0%`,
    });
    canvas.append(draft);

    const onMove = (moveEvent) => {
      if (!draft) return;
      const curX = Math.max(
        0,
        Math.min(100, ((moveEvent.clientX - bounds.left) / bounds.width) * 100)
      );
      const curY = Math.max(
        0,
        Math.min(100, ((moveEvent.clientY - bounds.top) / bounds.height) * 100)
      );
      const left = Math.min(startX, curX);
      const top = Math.min(startY, curY);
      const width = Math.abs(curX - startX);
      const height = Math.abs(curY - startY);
      draft.style.left = `${left}%`;
      draft.style.top = `${top}%`;
      draft.style.width = `${width}%`;
      draft.style.height = `${height}%`;
    };

    const onUp = (upEvent) => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      if (!draft) return;
      const curX = Math.max(
        0,
        Math.min(100, ((upEvent.clientX - bounds.left) / bounds.width) * 100)
      );
      const curY = Math.max(
        0,
        Math.min(100, ((upEvent.clientY - bounds.top) / bounds.height) * 100)
      );
      const x = Math.round(Math.min(startX, curX) * 100) / 100;
      const y = Math.round(Math.min(startY, curY) * 100) / 100;
      const w = Math.round(Math.abs(curX - startX) * 100) / 100;
      const h = Math.round(Math.abs(curY - startY) * 100) / 100;
      draft.remove();
      draft = null;
      if (w < 1.2 || h < 1.0) return;

      const noteInput = window.prompt(
        i18n.t("annotate.prompt"),
        i18n.t("annotate.defaultNote")
      );
      if (noteInput === null) return;
      const note = noteInput.trim() || i18n.t("annotate.defaultNote");
      state.annotations.push({
        id: state.nextAnnotationId++,
        pairIdx,
        side: side === "xray" ? "both" : "both",
        x,
        y,
        w,
        h,
        note,
      });
      syncActiveTab();
      if ($("#annotate-clear")) $("#annotate-clear").hidden = false;
      renderPages();
      collectChanges();
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });
}

/* ---------- change navigation (n / p, F3 / Shift+F3) ---------- */
function collectChanges() {
  if (!state.comparison) {
    state.changes = [];
    state.changeIndex = -1;
    updateChangeNav();
    return;
  }
  if (state.mode === "pages" || state.mode === "xray") {
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
  const prevMode = state.mode;
  state.mode = mode;
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
  const isPageMode = mode === "pages" || mode === "xray";
  $("#text-view").hidden = mode !== "text";
  $("#page-view").hidden = !isPageMode;
  $("#only-diff-wrap").hidden = mode !== "text";
  $("#zoom-wrap").hidden = !isPageMode;
  $("#box-color-wrap").hidden = !isPageMode;
  if ($("#annotate-wrap")) $("#annotate-wrap").hidden = !isPageMode;
  if ($("#annotate-clear")) {
    $("#annotate-clear").hidden = !isPageMode || !(state.annotations && state.annotations.length);
  }
  if (state.comparison && (prevMode !== mode) && isPageMode) {
    renderPages();
  }
  applyZoom();
  collectChanges();
  syncActiveTab();

  if (state.comparison && state.comparison.id) {
    const view = mode === "pages" ? "&view=pages" : mode === "xray" ? "&view=xray" : "";
    history.replaceState(
      null,
      "",
      `${location.pathname}?id=${state.comparison.id}${view}&lang=${i18n.lang}`
    );
  }
}

/* ---------- box outline color ---------- */
const BOX_COLOR_KEY = "diffanydoc:box-color";
const BOX_COLORS = ["amber", "ruby", "blue", "contrast"];

function applyBoxColor(name) {
  const color = BOX_COLORS.includes(name) ? name : "amber";
  document.body.dataset.boxColor = color;
  for (const item of $$("#box-color-menu [data-color]")) {
    const active = item.dataset.color === color;
    item.classList.toggle("active", active);
    item.setAttribute("aria-checked", String(active));
  }
}

function setupBoxColor() {
  let saved = null;
  try {
    saved = localStorage.getItem(BOX_COLOR_KEY);
  } catch (_) {
    /* storage may be blocked */
  }
  applyBoxColor(saved);
  for (const item of $$("#box-color-menu [data-color]")) {
    item.addEventListener("click", () => {
      closeMenus();
      applyBoxColor(item.dataset.color);
      try {
        localStorage.setItem(BOX_COLOR_KEY, item.dataset.color);
      } catch (_) {
        /* storage may be blocked */
      }
    });
  }
}

/* ---------- page zoom / pan ---------- */
const ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4];
const PT_TO_PX = 96 / 72;

function isPageMode() {
  return state.mode === "pages" || state.mode === "xray";
}

function clampZoom(value) {
  return Math.min(4, Math.max(0.25, value));
}

/* Largest page in PDF points. */
function pageExtent() {
  const pages = (state.comparison && state.comparison.pages) || {};
  let width = 0;
  let height = 0;
  for (const side of ["left", "right"]) {
    for (const page of Object.values(pages[side] || {})) {
      if (!page) continue;
      width = Math.max(width, page.width);
      height = Math.max(height, page.height);
    }
  }
  return { width: width || 595, height: height || 842 };
}

function canvasStyle(size) {
  return (
    `width:calc(${(size.width * PT_TO_PX).toFixed(2)}px * var(--zoom, 1));` +
    `aspect-ratio:${size.width} / ${size.height}`
  );
}

function missingCanvas() {
  return el("div", {
    class: "page-canvas missing",
    style: canvasStyle(pageExtent()),
    text: i18n.t("page.missing"),
  });
}

/* Render DPI follows zoom so small print stays sharp. */
function pageDpi() {
  const need = 96 * state.zoomValue * (window.devicePixelRatio || 1);
  return Math.max(120, Math.min(300, Math.ceil(need / 30) * 30));
}

function pageImage(base, alt) {
  return el("img", {
    src: `${base}?dpi=${pageDpi()}`,
    "data-base": base,
    alt,
    loading: "lazy",
  });
}

let dpiTimer = 0;
function scheduleDpiUpdate() {
  clearTimeout(dpiTimer);
  dpiTimer = setTimeout(() => {
    const dpi = pageDpi();
    for (const img of $$("#page-view img[data-base]")) {
      const next = `${img.dataset.base}?dpi=${dpi}`;
      if (img.getAttribute("src") !== next) img.src = next;
    }
  }, 250);
}

function resolveZoom() {
  if (typeof state.zoom === "number") return state.zoom;
  const view = $("#page-view");
  if (!view.clientWidth) return state.zoomValue;
  const extent = pageExtent();
  const cols = state.mode === "xray" ? 1 : 2;
  const style = getComputedStyle(view);
  const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  const row = view.querySelector(".page-row");
  const gap = row ? parseFloat(getComputedStyle(row).columnGap) || 0 : 0;
  const card = view.querySelector(".page-card");
  const cardStyle = card ? getComputedStyle(card) : null;
  const chrome = cardStyle
    ? parseFloat(cardStyle.paddingLeft) +
      parseFloat(cardStyle.paddingRight) +
      parseFloat(cardStyle.borderLeftWidth) +
      parseFloat(cardStyle.borderRightWidth)
    : 0;
  const avail = view.clientWidth - padding - cols * chrome - (cols - 1) * gap - 1;
  let zoom = avail / (cols * extent.width * PT_TO_PX);
  if (state.zoom === "page") {
    const top = $(".topbar").offsetHeight + $(".result-head").offsetHeight;
    const label = 40;
    zoom = Math.min(
      zoom,
      (window.innerHeight - top - label) / (extent.height * PT_TO_PX)
    );
  }
  return clampZoom(zoom);
}

function applyZoom() {
  state.zoomValue = resolveZoom();
  $("#page-view").style.setProperty("--zoom", String(state.zoomValue));
  $("#zoom-label").textContent = `%${Math.round(state.zoomValue * 100)}`;
  $("#zoom-fit-width").setAttribute("aria-pressed", String(state.zoom === "width"));
  $("#zoom-fit-page").setAttribute("aria-pressed", String(state.zoom === "page"));
  scheduleDpiUpdate();
}

/* Keep the point under the anchor fixed. */
function setZoom(value, anchor) {
  const view = $("#page-view");
  const before = state.zoomValue;
  const rect = view.getBoundingClientRect();
  const x = (anchor ? anchor.x : rect.left + view.clientWidth / 2) - rect.left;
  const y = (anchor ? anchor.y : window.innerHeight / 2) - rect.top;
  const scrollLeft = view.scrollLeft;
  state.zoom = typeof value === "number" ? clampZoom(value) : value;
  applyZoom();
  syncActiveTab();
  const ratio = state.zoomValue / before;
  view.scrollLeft = (scrollLeft + x) * ratio - x;
  window.scrollBy(0, y * (ratio - 1));
}

function stepZoom(direction) {
  const current = state.zoomValue;
  const next =
    direction > 0
      ? ZOOM_STEPS.find((step) => step > current + 0.001)
      : [...ZOOM_STEPS].reverse().find((step) => step < current - 0.001);
  setZoom(next === undefined ? current : next);
}

const pan = { ready: false };

function setPanReady(ready) {
  pan.ready = ready;
  document.body.classList.toggle("pan-ready", ready);
}

function setupPageZoom() {
  const view = $("#page-view");

  view.addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
      setZoom(state.zoomValue * factor, { x: event.clientX, y: event.clientY });
    },
    { passive: false }
  );

  // Capture phase: panning wins over annotation drawing.
  view.addEventListener(
    "mousedown",
    (event) => {
      if (!(event.button === 1 || (event.button === 0 && pan.ready))) return;
      event.preventDefault();
      event.stopPropagation();
      let lastX = event.clientX;
      let lastY = event.clientY;
      document.body.classList.add("panning");
      const onMove = (move) => {
        view.scrollLeft -= move.clientX - lastX;
        window.scrollBy(0, -(move.clientY - lastY));
        lastX = move.clientX;
        lastY = move.clientY;
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        document.body.classList.remove("panning");
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    true
  );
  // No middle-click autoscroll or paste.
  view.addEventListener("auxclick", (event) => {
    if (event.button === 1) event.preventDefault();
  });

  document.addEventListener("keyup", (event) => {
    if (event.key === " ") setPanReady(false);
  });
  window.addEventListener("blur", () => setPanReady(false));
  window.addEventListener("resize", () => {
    if (state.comparison && isPageMode() && typeof state.zoom !== "number") {
      applyZoom();
    }
  });

  $("#zoom-in").addEventListener("click", () => stepZoom(1));
  $("#zoom-out").addEventListener("click", () => stepZoom(-1));
  $("#zoom-reset").addEventListener("click", () => setZoom(1));
  $("#zoom-fit-width").addEventListener("click", () => setZoom("width"));
  $("#zoom-fit-page").addEventListener("click", () => setZoom("page"));
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
  $("#box-color-wrap").hidden = true;
  if ($("#annotate-wrap")) $("#annotate-wrap").hidden = true;
  if ($("#annotate-clear")) $("#annotate-clear").hidden = true;
  $("#change-nav").hidden = true;
  $("#stats").replaceChildren();
  state.visual = null;
  state.ocr = null;
  for (const node of $$("[data-result-only]")) node.hidden = true;
  closeMenus();
  hideError();
  updateCompareButton();
  window.scrollTo({ top: 0 });
}

function reset() {
  state.files = { left: null, right: null };
  desktop.paths = { left: null, right: null };
  state.preloadedHashes = { left: "", right: "" };
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
  if ($("#opt-ocr")) $("#opt-ocr").checked = false;
  if ($("#opt-format")) $("#opt-format").checked = false;
  if ($("#opt-ocr-lang")) $("#opt-ocr-lang").hidden = true;
  state.annotations = [];
  state.annotating = false;
  if ($("#opt-annotate")) $("#opt-annotate").checked = false;
  document.body.classList.remove("annotating");
  document.body.classList.remove("dragging");
  showUploadView();
  updateCompareButton();
  syncActiveTab();
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
  openExternal(event, $("#export").getAttribute("href"));
});

/* ---------- wiring ---------- */
setupDropZones();
setupMenus();
setupDialogs();
loadTheme();
$("#compare").addEventListener("click", runComparison);
$("#restart").addEventListener("click", reset);
if ($("#new-compare-btn")) $("#new-compare-btn").addEventListener("click", reset);
if ($("#add-tab")) $("#add-tab").addEventListener("click", createNewSessionTab);
if ($("#new-tab-btn")) $("#new-tab-btn").addEventListener("click", createNewSessionTab);
if ($("#new-tab-menu")) $("#new-tab-menu").addEventListener("click", createNewSessionTab);
$("#reload").addEventListener("click", reloadComparison);
if ($("#copy-all-to-right")) $("#copy-all-to-right").addEventListener("click", () => mergeAllToSide("left"));
if ($("#copy-all-to-left")) $("#copy-all-to-left").addEventListener("click", () => mergeAllToSide("right"));
$("#copy-changes").addEventListener("click", () => copyView("changes"));
$("#copy-left").addEventListener("click", () => copyView("left"));
$("#copy-right").addEventListener("click", () => copyView("right"));
$("#copy-both").addEventListener("click", () => copyView("both"));
if ($("#download-left")) $("#download-left").addEventListener("click", () => downloadSideDocument("left"));
if ($("#download-right")) $("#download-right").addEventListener("click", () => downloadSideDocument("right"));

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

if ($("#opt-annotate")) {
  $("#opt-annotate").addEventListener("change", (event) => {
    state.annotating = Boolean(event.target.checked);
    document.body.classList.toggle("annotating", state.annotating);
  });
}

if ($("#annotate-clear")) {
  $("#annotate-clear").addEventListener("click", clearManualAnnotations);
}

if ($("#opt-ocr")) {
  $("#opt-ocr").addEventListener("change", (event) => {
    const select = $("#opt-ocr-lang");
    if (select) select.hidden = !event.target.checked;
  });
}

async function loadOcrStatus() {
  const select = $("#opt-ocr-lang");
  if (!select) return;
  try {
    const response = await fetch("/api/ocr/status");
    if (!response.ok) return;
    const payload = await response.json();
    if (Array.isArray(payload.languages) && payload.languages.length) {
      select.replaceChildren(
        ...payload.languages.map((code) =>
          el("option", { value: code, text: code })
        )
      );
      if (i18n.lang === "tr" && payload.languages.includes("tur+eng")) {
        select.value = "tur+eng";
      }
    }
  } catch (_) {
    /* keep default language list */
  }
}

setupPageZoom();
setupBoxColor();

$("#prev-change").addEventListener("click", () => gotoChange(-1));
$("#next-change").addEventListener("click", () => gotoChange(1));

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    if ($("#upload-view").hidden === false) runComparison();
    return;
  }

  if (event.key === "F1") {
    event.preventDefault();
    openHelp();
    return;
  }

  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "o" &&
    !$("#upload-view").hidden
  ) {
    event.preventDefault();
    const empty = !(state.files.left || desktop.paths.left) ? "left"
      : !(state.files.right || desktop.paths.right) ? "right" : "left";
    chooseFile(empty);
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "w") {
    event.preventDefault();
    closeSessionTab(state.activeTabId);
    return;
  }

  const pageZoomKeys = state.comparison && isPageMode() && !$("#result-view").hidden;
  if ((event.ctrlKey || event.metaKey) && pageZoomKeys) {
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      stepZoom(1);
      return;
    }
    if (event.key === "-") {
      event.preventDefault();
      stepZoom(-1);
      return;
    }
    if (event.key === "0") {
      event.preventDefault();
      setZoom(1);
      return;
    }
  }

  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const tag = (event.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable) {
    return;
  }
  if ($("#result-view").hidden) return;

  // Space + drag pans; buttons keep Space.
  if (event.key === " " && pageZoomKeys && tag !== "button") {
    event.preventDefault();
    if (!event.repeat) setPanReady(true);
    return;
  }

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
  await loadOcrStatus();
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
