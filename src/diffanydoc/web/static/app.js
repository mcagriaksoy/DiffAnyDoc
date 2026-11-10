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
  search: {
    query: "",
    matches: [],
    index: -1,
    filter: "all",
  },
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

/* ---------- safe storage helpers ---------- */
function safeStorageGet(key, fallback = null) {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      const val = window.localStorage.getItem(key);
      return val !== null ? val : fallback;
    }
  } catch (_) {}
  return fallback;
}

function safeStorageSet(key, value) {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem(key, String(value));
    }
  } catch (_) {}
}

/* ---------- language ---------- */
function preferredLanguage() {
  const fromUrl = new URLSearchParams(location.search).get("lang");
  if (fromUrl) return fromUrl;
  const saved = safeStorageGet(LANG_KEY);
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
      safeStorageSet(LANG_KEY, code);
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

function showLicensePanel(name) {
  for (const tab of $$(".license-tab")) {
    const active = tab.dataset.license === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  for (const panel of $$(".license-panel")) {
    panel.hidden = panel.dataset.licensePanel !== name;
  }
}

function openLicense() {
  closeMenus();
  showLicensePanel("terms");
  const dialog = $("#license-dialog");
  if (!dialog.open) dialog.showModal();
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
  try {
    for (const dialog of $$("dialog")) {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
      });
      for (const button of dialog.querySelectorAll("[data-close]")) {
        button.addEventListener("click", () => dialog.close());
      }
    }

    if ($("#about")) {
      $("#about").addEventListener("click", () => {
        closeMenus();
        fillAbout();
        if ($("#about-dialog")) $("#about-dialog").showModal();
      });
    }
    if ($("#about-license")) {
      $("#about-license").addEventListener("click", () => {
        if ($("#about-dialog")) $("#about-dialog").close();
        openLicense();
      });
    }
    if ($("#license")) $("#license").addEventListener("click", openLicense);
    for (const tab of $$(".license-tab")) {
      tab.addEventListener("click", () => showLicensePanel(tab.dataset.license));
    }
    if ($("#help")) $("#help").addEventListener("click", openHelp);
    for (const tab of $$(".help-tab")) {
      tab.addEventListener("click", () => showHelpPanel(tab.dataset.help));
    }
    if ($("#updates")) {
      $("#updates").addEventListener("click", () => {
        closeMenus();
        fillUpdates();
        if ($("#updates-dialog")) $("#updates-dialog").showModal();
        checkUpdates();
      });
    }
    if ($("#updates-check")) $("#updates-check").addEventListener("click", checkUpdates);
    if ($("#updates-open")) {
      $("#updates-open").addEventListener("click", (event) =>
        openExternal(event, $("#updates-open").getAttribute("href"))
      );
    }
    if ($("#settings-menu-btn")) {
      $("#settings-menu-btn").addEventListener("click", openSettings);
    }
    if ($("#settings-integrate-toggle")) {
      $("#settings-integrate-toggle").addEventListener("click", toggleIntegration);
    }
    if ($("#settings-pending-clear")) {
      $("#settings-pending-clear").addEventListener("click", clearPendingSelection);
    }
    if ($("#integrate-menu")) {
      $("#integrate-menu").addEventListener("click", toggleIntegration);
    }
  } catch (_) {}
}

function openSettings() {
  closeMenus();
  loadIntegrationStatus();
  if ($("#settings-dialog")) $("#settings-dialog").showModal();
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
      await processDroppedData(e.dataTransfer, side);
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
    await processDroppedData(e.dataTransfer, null);
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

async function processDroppedData(dataTransfer, preferredSide) {
  if (!dataTransfer) return false;

  // 1. In desktop mode, first check if text/uri-list or text/plain or files contain local OS paths
  if (desktop.available && window.pywebview && window.pywebview.api) {
    const raw =
      dataTransfer.getData("text/uri-list") ||
      dataTransfer.getData("text/plain") ||
      "";
    if (raw.trim()) {
      try {
        const resolved = await window.pywebview.api.resolve_dropped_uris(raw);
        if (Array.isArray(resolved) && resolved.length > 0) {
          applyResolvedDesktopPaths(resolved, preferredSide);
          return true;
        }
      } catch (_) {}
    }

    // Check if DataTransfer files object has OS path properties (WebKit2GTK / Electron)
    const dtFiles = Array.from(dataTransfer.files || []);
    const filePaths = dtFiles
      .map((f) => f.pywebviewFullPath || f.path)
      .filter((p) => Boolean(p && typeof p === "string"));
    if (filePaths.length > 0) {
      applyResolvedDesktopPaths(filePaths, preferredSide);
      return true;
    }
  }

  // 2. Standard browser File objects fallback
  const files = Array.from(dataTransfer.files || []);
  if (files.length > 0) {
    assignDroppedFiles(files, preferredSide);
    return true;
  }

  return false;
}

function applyResolvedDesktopPaths(resolved, preferredSide) {
  if (!Array.isArray(resolved) || !resolved.length) return;
  if (resolved.length >= 2) {
    desktop.paths.left = resolved[0];
    desktop.paths.right = resolved[1];
    showPath("left", resolved[0]);
    showPath("right", resolved[1]);
  } else {
    const side =
      preferredSide ||
      (!hasFile("left") ? "left" : !hasFile("right") ? "right" : "left");
    desktop.paths[side] = resolved[0];
    showPath(side, resolved[0]);
  }
  if (!$("#result-view").hidden) showUploadView();
  updateCompareButton();
}

async function handleUriDrop(dataTransfer, preferredSide) {
  return processDroppedData(dataTransfer, preferredSide);
}

function assignDroppedFiles(files, preferredSide) {
  if (!files.length) return;
  if (files.length >= 2) {
    setFile("left", files[0]);
    setFile("right", files[1]);
  } else {
    const side =
      preferredSide ||
      (!hasFile("left") ? "left" : !hasFile("right") ? "right" : "left");
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

function hasFile(side) {
  return Boolean((desktop.available && desktop.paths[side]) || state.files[side]);
}

function isReady() {
  return hasFile("left") && hasFile("right");
}

function canReload() {
  return isReady();
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
  const caseSensitive = $("#opt-case") ? !$("#opt-case").checked : true;
  const collapseWhitespace = $("#opt-space") ? $("#opt-space").checked : true;
  const formatCheckbox = $("#opt-format");
  const compareFormatting = Boolean(formatCheckbox && formatCheckbox.checked);
  const ocrCheckbox = $("#opt-ocr");
  const ocr = ocrCheckbox ? Boolean(ocrCheckbox.checked) : true;
  const ocrLangSelect = $("#opt-ocr-lang");
  const ocrLanguage = (ocrLangSelect && ocrLangSelect.value) || (i18n.lang === "tr" ? "tur+eng" : "eng");
  const tolInput = $("#opt-tolerance");
  let numericTolerance = null;
  if (tolInput && tolInput.value && tolInput.value.trim() !== "") {
    const parsed = parseFloat(tolInput.value);
    if (Number.isFinite(parsed) && parsed >= 0) numericTolerance = parsed;
  }

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
        numeric_tolerance: numericTolerance,
      }),
    });
  }

  const form = new FormData();
  if (desktop.available && desktop.paths.left) {
    form.append("left_path", desktop.paths.left);
  } else if (state.files.left) {
    form.append("left", state.files.left);
  }

  if (desktop.available && desktop.paths.right) {
    form.append("right_path", desktop.paths.right);
  } else if (state.files.right) {
    form.append("right", state.files.right);
  }

  form.append("case_sensitive", String(caseSensitive));
  form.append("collapse_whitespace", String(collapseWhitespace));
  form.append("compare_formatting", String(compareFormatting));
  form.append("fold_equal", "false");
  form.append("context", "3");
  form.append("visual", "true");
  form.append("ocr", String(ocr));
  form.append("ocr_language", ocrLanguage);
  if (numericTolerance !== null) {
    form.append("numeric_tolerance", String(numericTolerance));
  }
  return fetch("/api/compare", { method: "POST", body: form });
}

function setComparing(active) {
  state.comparing = active;
  const button = $("#compare");
  if (button) {
    const spinner = button.querySelector(".spinner");
    button.disabled = active || !isReady();
    if (spinner) spinner.hidden = !active;
  }
  const reload = $("#reload");
  if (reload) reload.disabled = active;
}

async function runComparison() {
  if (state.comparing) return;
  if (!isReady()) {
    showError(i18n.t("error.generic"));
    return;
  }
  hideError();
  setComparing(true);

  if (desktop.available && desktop.paths.left && desktop.paths.right) {
    const isDoc = /\.(pdf|docx?|odt|rtf|xlsx?|xlsm|csv|tsv|png|jpe?g|tiff?|bmp|webp|txt|md|json|py|js|html?|css|xml|c|cpp|h|rs|go|java)$/i;
    const bothAreDocs = isDoc.test(desktop.paths.left) && isDoc.test(desktop.paths.right);
    if (!bothAreDocs) {
      try {
        const dirResp = await fetch("/api/compare-directories", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ left: desktop.paths.left, right: desktop.paths.right }),
        });
        if (dirResp.ok) {
          const folderData = await dirResp.json();
          renderFolderDiff(folderData);
          setComparing(false);
          updateCompareButton();
          return;
        }
      } catch (_) {
        /* not directories, proceed to regular document compare */
      }
    }
  }

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
  const stickyHeader = $(".result-sticky-header");
  if (stickyHeader) stickyHeader.hidden = false;
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
  if ($("#export-pdf")) {
    $("#export-pdf").href = `/api/compare/${data.id}/report.pdf?lang=${i18n.lang}`;
  }

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
  const statsContainer = $("#stats");
  statsContainer.replaceChildren(...nodes);
  statsContainer.setAttribute("role", "button");
  statsContainer.setAttribute("tabindex", "0");
  statsContainer.setAttribute("title", i18n.t("stats.openDetails"));
}

function openStatsDetails() {
  const dialog = $("#stats-detail-dialog");
  if (!dialog || !state.comparison) return;

  const data = state.comparison;
  const stats = data.stats || {};
  const docAName = data.left ? data.left.name : "Document A";
  const docBName = data.right ? data.right.name : "Document B";

  const thA = $("#stats-th-doc-a");
  const thB = $("#stats-th-doc-b");
  if (thA) thA.textContent = docAName;
  if (thB) thB.textContent = docBName;

  const tbody = $("#stats-detail-tbody");
  if (tbody) {
    tbody.replaceChildren();

    const diffFmt = (diff) => {
      if (diff > 0) return `+${diff}`;
      if (diff < 0) return `${diff}`;
      return "0";
    };

    const wordsDiff = (stats.right_words || 0) - (stats.left_words || 0);
    const charsDiff = (stats.right_chars || 0) - (stats.left_chars || 0);
    const linesDiff = (stats.right_lines || 0) - (stats.left_lines || 0);
    const readDiff = (stats.right_reading_time_min || 0) - (stats.left_reading_time_min || 0);

    const rows = [
      {
        name: i18n.t("stats.words"),
        a: (stats.left_words || 0).toLocaleString(),
        b: (stats.right_words || 0).toLocaleString(),
        diff: diffFmt(wordsDiff),
      },
      {
        name: i18n.t("stats.chars"),
        a: (stats.left_chars || 0).toLocaleString(),
        b: (stats.right_chars || 0).toLocaleString(),
        diff: diffFmt(charsDiff),
      },
      {
        name: i18n.t("stats.readingTime"),
        a: i18n.t("stats.readingTimeVal", { min: (stats.left_reading_time_min || 0).toFixed(1) }),
        b: i18n.t("stats.readingTimeVal", { min: (stats.right_reading_time_min || 0).toFixed(1) }),
        diff: `${readDiff >= 0 ? "+" : ""}${readDiff.toFixed(1)} min`,
      },
      {
        name: i18n.t("stats.lines"),
        a: (stats.left_lines || 0).toLocaleString(),
        b: (stats.right_lines || 0).toLocaleString(),
        diff: diffFmt(linesDiff),
      },
    ];

    for (const r of rows) {
      const tr = el("tr", {}, [
        el("td", { text: r.name, style: "font-weight: 500;" }),
        el("td", { text: r.a }),
        el("td", { text: r.b }),
        el("td", {
          text: r.diff,
          style: r.diff.startsWith("+")
            ? "color: var(--diff-ins-strong); font-weight: 600;"
            : r.diff.startsWith("-")
              ? "color: var(--diff-del-strong); font-weight: 600;"
              : "color: var(--dim-label-color);",
        }),
      ]);
      tbody.appendChild(tr);
    }
  }

  const breakdown = $("#stats-breakdown");
  if (breakdown) {
    breakdown.replaceChildren(
      el("div", { class: "breakdown-card" }, [
        el("div", { class: "b-label", text: i18n.t("stats.wordsAdded") }),
        el("div", { class: "b-val", text: `+${stats.words_added || 0}`, style: "color: var(--diff-ins-strong);" }),
      ]),
      el("div", { class: "breakdown-card" }, [
        el("div", { class: "b-label", text: i18n.t("stats.wordsRemoved") }),
        el("div", { class: "b-val", text: `−${stats.words_removed || 0}`, style: "color: var(--diff-del-strong);" }),
      ]),
      el("div", { class: "breakdown-card" }, [
        el("div", { class: "b-label", text: i18n.t("stats.changeDensity") }),
        el("div", { class: "b-val", text: `${((stats.change_density || 0) * 100).toFixed(1)}%`, style: "color: var(--accent-color);" }),
      ])
    );
  }

  dialog.showModal();
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

  const canvas = el("div", { class: "page-canvas is-loading", style: canvasStyle(size) }, [
    el("div", { class: "canvas-spinner", "aria-label": i18n.t("state.loading") }, [
      el("span", { class: "canvas-spinner-icon", "aria-hidden": "true" }),
      el("span", { class: "canvas-spinner-label", text: i18n.t("state.loading") }),
    ]),
  ]);
  canvas.append(
    pageImage(
      `/api/compare/${data.id}/xray/${pair.left}/${pair.right}.png`,
      `${label} ${pageText}`,
      pairIdx === 0
    )
  );

  // Also show OCR/text diff boxes and visual boxes so hovering shows the text
  const rectsL = (data.rects.left && data.rects.left[String(pair.left)]) || [];
  const rectsR = (data.rects.right && data.rects.right[String(pair.right)]) || [];
  const combinedRects = [...rectsL, ...rectsR];
  const xrayRowsWithWords = new Set(
    combinedRects.filter((r) => r.level === "word").map((r) => r.row)
  );
  const activeXrayRects = combinedRects.filter(
    (r) => !(r.level === "line" && xrayRowsWithWords.has(r.row))
  );
  for (const rect of activeXrayRects) {
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
  const canvas = el("div", { class: "page-canvas is-loading", style: canvasStyle(size) }, [
    el("div", { class: "canvas-spinner", "aria-label": i18n.t("state.loading") }, [
      el("span", { class: "canvas-spinner-icon", "aria-hidden": "true" }),
      el("span", { class: "canvas-spinner-label", text: i18n.t("state.loading") }),
    ]),
  ]);
  canvas.append(
    pageImage(
      `/api/compare/${data.id}/page/${side}/${index}.png`,
      `${name} ${i18n.t("page.label", { n: index + 1 })}`,
      pairIdx === 0
    )
  );

  const rects = (data.rects[side] && data.rects[side][String(index)]) || [];
  const rowsWithWords = new Set(
    rects.filter((r) => r.level === "word").map((r) => r.row)
  );
  const activeRects = rects.filter(
    (r) => !(r.level === "line" && rowsWithWords.has(r.row))
  );
  for (const rect of activeRects) {
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
  renderMinimap();
}

function updateChangeNav() {
  const count = state.changes.length;
  const current = count === 0 ? 0 : Math.max(state.changeIndex + 1, 0);
  const text = i18n.t("nav.position", { current, total: count });

  const nav = $("#change-nav");
  if (nav) {
    nav.hidden = count === 0;
    const cnt = $("#change-count");
    if (cnt) cnt.textContent = text;
    const prev = $("#prev-change");
    const next = $("#next-change");
    if (prev) prev.disabled = count === 0;
    if (next) next.disabled = count === 0;
  }

  const topNav = $("#top-diff-nav");
  if (topNav) {
    topNav.hidden = count === 0;
    const topCnt = $("#top-change-count");
    if (topCnt) topCnt.textContent = text;
    const topPrev = $("#top-prev-change");
    const topNext = $("#top-next-change");
    if (topPrev) topPrev.disabled = count === 0;
    if (topNext) topNext.disabled = count === 0;
  }
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

/* ---------- diff overview minimap (TASK-14) ---------- */
function renderMinimap() {
  const minimap = $("#diff-minimap");
  const track = $("#minimap-track");
  if (!minimap || !track) return;

  if ($("#result-view").hidden || !state.comparison || !state.changes.length) {
    minimap.hidden = true;
    return;
  }

  minimap.hidden = false;
  const viewport = $("#minimap-viewport");
  track.replaceChildren(viewport);

  const docHeight = Math.max(
    document.documentElement.scrollHeight,
    document.body.scrollHeight,
    window.innerHeight
  );
  const trackHeight = track.clientHeight || (window.innerHeight - 48);

  const fragment = document.createDocumentFragment();
  for (const node of state.changes) {
    const rect = node.getBoundingClientRect();
    const elemTop = rect.top + window.scrollY;
    const ratio = Math.min(Math.max(elemTop / docHeight, 0), 1);
    const topPx = Math.round(ratio * trackHeight);

    let kind = "mod";
    if (node.classList.contains("add")) kind = "add";
    else if (node.classList.contains("del")) kind = "del";
    else if (node.classList.contains("mod")) kind = "mod";

    const mark = el("div", {
      class: `minimap-mark ${kind}`,
      style: `top: ${topPx}px`,
    });
    fragment.appendChild(mark);
  }
  track.appendChild(fragment);
  updateMinimapViewport();
}

function updateMinimapViewport() {
  const minimap = $("#diff-minimap");
  const track = $("#minimap-track");
  const viewport = $("#minimap-viewport");
  if (!minimap || minimap.hidden || !track || !viewport) return;

  const docHeight = Math.max(
    document.documentElement.scrollHeight,
    document.body.scrollHeight,
    window.innerHeight
  );
  const trackHeight = track.clientHeight || (window.innerHeight - 48);
  const scrollY = window.scrollY;
  const viewHeight = window.innerHeight;

  const topRatio = Math.min(Math.max(scrollY / docHeight, 0), 1);
  const heightRatio = Math.min(Math.max(viewHeight / docHeight, 0.04), 1);

  viewport.style.top = `${Math.round(topRatio * trackHeight)}px`;
  viewport.style.height = `${Math.round(heightRatio * trackHeight)}px`;
}

function setupMinimap() {
  const minimap = $("#diff-minimap");
  const track = $("#minimap-track");
  if (!minimap || !track) return;

  let isDragging = false;

  function scrollToMinimapPos(clientY) {
    const rect = track.getBoundingClientRect();
    const offsetY = clientY - rect.top;
    const ratio = Math.min(Math.max(offsetY / rect.height, 0), 1);
    const docHeight = Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight,
      window.innerHeight
    );
    window.scrollTo({
      top: ratio * docHeight - window.innerHeight / 2,
      behavior: isDragging ? "auto" : "smooth",
    });
  }

  minimap.addEventListener("mousedown", (e) => {
    isDragging = true;
    scrollToMinimapPos(e.clientY);
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    scrollToMinimapPos(e.clientY);
  });

  window.addEventListener("mouseup", () => {
    isDragging = false;
  });

  window.addEventListener("scroll", updateMinimapViewport, { passive: true });
  window.addEventListener("resize", () => {
    if (!minimap.hidden) renderMinimap();
  });
}

/* ---------- in-document search & filtering (TASK-15) ---------- */
function clearSearchHighlights() {
  const marks = Array.from(document.querySelectorAll("#text-view mark.search-match"));
  for (const mark of marks) {
    const parent = mark.parentNode;
    if (parent) {
      mark.replaceWith(document.createTextNode(mark.textContent));
      parent.normalize();
    }
  }
}

function highlightTextInContainer(container, lowerQ, matchLen) {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) {
    textNodes.push(node);
  }

  for (const textNode of textNodes) {
    const str = textNode.nodeValue;
    const lowerStr = str.toLowerCase();
    let idx = lowerStr.indexOf(lowerQ);
    if (idx === -1) continue;

    const parent = textNode.parentNode;
    const fragment = document.createDocumentFragment();
    let lastIdx = 0;

    while (idx !== -1) {
      if (idx > lastIdx) {
        fragment.appendChild(document.createTextNode(str.slice(lastIdx, idx)));
      }
      const mark = document.createElement("mark");
      mark.className = "search-match";
      mark.textContent = str.slice(idx, idx + matchLen);
      fragment.appendChild(mark);
      lastIdx = idx + matchLen;
      idx = lowerStr.indexOf(lowerQ, lastIdx);
    }
    if (lastIdx < str.length) {
      fragment.appendChild(document.createTextNode(str.slice(lastIdx)));
    }
    parent.replaceChild(fragment, textNode);
  }
}

function updateSearchCount() {
  const countEl = $("#search-count");
  if (!countEl) return;
  const total = state.search.matches.length;
  const current = total === 0 ? 0 : state.search.index + 1;
  countEl.textContent = `${current} / ${total}`;
}

function performSearch(query) {
  clearSearchHighlights();
  state.search.matches = [];
  state.search.index = -1;
  const q = (query || "").trim();
  state.search.query = q;
  if (!q) {
    updateSearchCount();
    return;
  }

  const rows = Array.from(document.querySelectorAll("#text-view .row"));
  const lowerQ = q.toLowerCase();

  for (const row of rows) {
    if (row.offsetParent === null) continue; // Skip hidden rows
    const textContainers = row.querySelectorAll(".cell .text");
    for (const container of textContainers) {
      highlightTextInContainer(container, lowerQ, q.length);
    }
  }

  state.search.matches = Array.from(document.querySelectorAll("#text-view mark.search-match"));
  if (state.search.matches.length > 0) {
    state.search.index = 0;
    state.search.matches[0].classList.add("active");
    state.search.matches[0].scrollIntoView({
      block: "center",
      behavior: reducedMotion() ? "auto" : "smooth",
    });
  }
  updateSearchCount();
}

function navigateSearch(delta) {
  if (!state.search.matches.length) return;
  if (state.search.matches[state.search.index]) {
    state.search.matches[state.search.index].classList.remove("active");
  }
  state.search.index =
    (state.search.index + delta + state.search.matches.length) % state.search.matches.length;
  const current = state.search.matches[state.search.index];
  if (current) {
    current.classList.add("active");
    current.scrollIntoView({
      block: "center",
      behavior: reducedMotion() ? "auto" : "smooth",
    });
  }
  updateSearchCount();
}

function openSearch() {
  const bar = $("#search-bar");
  if (!bar) return;
  bar.hidden = false;
  const input = $("#search-input");
  if (input) {
    input.focus();
    input.select();
    if (input.value) performSearch(input.value);
  }
}

function closeSearch() {
  const bar = $("#search-bar");
  if (!bar) return;
  bar.hidden = true;
  clearSearchHighlights();
  state.search.matches = [];
  state.search.index = -1;
  updateSearchCount();
}

function toggleSearch() {
  const bar = $("#search-bar");
  if (!bar) return;
  if (bar.hidden) openSearch();
  else closeSearch();
}

function applyKindFilter(filterKind) {
  state.search.filter = filterKind;
  for (const chip of $$("#search-bar .filter-chip")) {
    chip.classList.toggle("active", chip.dataset.filter === filterKind);
  }
  const rows = $$("#text-view .row");
  for (const row of rows) {
    if (filterKind === "all") {
      row.style.display = "";
    } else if (filterKind === "add") {
      row.style.display = row.classList.contains("add") ? "" : "none";
    } else if (filterKind === "del") {
      row.style.display = row.classList.contains("del") ? "" : "none";
    } else if (filterKind === "mod") {
      row.style.display = row.classList.contains("mod") ? "" : "none";
    }
  }
  collectChanges();
  if (state.search.query) {
    performSearch(state.search.query);
  }
}

function setupSearch() {
  const toggleBtn = $("#search-toggle");
  if (toggleBtn) toggleBtn.addEventListener("click", toggleSearch);

  const closeBtn = $("#search-close");
  if (closeBtn) closeBtn.addEventListener("click", closeSearch);

  const prevBtn = $("#search-prev");
  if (prevBtn) prevBtn.addEventListener("click", () => navigateSearch(-1));

  const nextBtn = $("#search-next");
  if (nextBtn) nextBtn.addEventListener("click", () => navigateSearch(1));

  const input = $("#search-input");
  if (input) {
    input.addEventListener("input", (e) => {
      performSearch(e.target.value);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        navigateSearch(e.shiftKey ? -1 : 1);
      } else if (e.key === "Escape") {
        e.preventDefault();
        closeSearch();
      }
    });
  }

  for (const chip of $$("#search-bar .filter-chip")) {
    chip.addEventListener("click", () => {
      applyKindFilter(chip.dataset.filter);
    });
  }
}

/* ---------- view switches ---------- */
function setMode(mode) {
  const prevMode = state.mode;
  state.mode = mode;
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
  const isPageMode = mode === "pages" || mode === "xray";
  const isFolderMode = mode === "folder";
  $("#text-view").hidden = mode !== "text";
  $("#page-view").hidden = !isPageMode;
  if ($("#folder-view")) $("#folder-view").hidden = !isFolderMode;
  const stickyHeader = $(".result-sticky-header");
  if (stickyHeader) stickyHeader.hidden = isFolderMode;
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

function openFilePairInNewTab(leftPath, rightPath) {
  createNewSessionTab();
  desktop.paths.left = leftPath;
  desktop.paths.right = rightPath;
  showPath("left", leftPath);
  showPath("right", rightPath);
  updateCompareButton();
  runComparison();
}

function renderFolderDiff(folderData) {
  state.folderData = folderData;
  $("#upload-view").hidden = true;
  $("#result-view").hidden = false;
  $("#view-tabs").hidden = false;
  if ($("#tab-folder")) $("#tab-folder").hidden = false;
  $("#text-view").hidden = true;
  $("#page-view").hidden = true;
  if ($("#folder-view")) $("#folder-view").hidden = false;
  $("#tab-pages").disabled = true;
  if ($("#tab-xray")) $("#tab-xray").disabled = true;
  $("#only-diff-wrap").hidden = true;
  $("#zoom-wrap").hidden = true;
  $("#box-color-wrap").hidden = true;
  if ($("#top-diff-nav")) $("#top-diff-nav").hidden = true;
  if ($("#diff-minimap")) $("#diff-minimap").hidden = true;
  if ($("#folder-view")) $("#folder-view").hidden = false;
  if ($("#tab-folder")) $("#tab-folder").hidden = false;
  setMode("folder");

  const container = $("#folder-view");
  if (!container) return;
  container.replaceChildren();

  const head = el("div", { class: "folder-head" }, [
    el("div", { class: "folder-paths" }, [
      el("div", { class: "f-path" }, [el("strong", { text: "A: " }), el("span", { text: folderData.left_path })]),
      el("div", { class: "f-path" }, [el("strong", { text: "B: " }), el("span", { text: folderData.right_path })]),
    ]),
    el("div", { class: "folder-filters" }, [
      el("button", { class: "filter-chip active", "data-f-filter": "all", text: `${i18n.t("folder.filterAll")} (${folderData.total_count})` }),
      el("button", { class: "filter-chip chip-mod", "data-f-filter": "modified", text: `${i18n.t("folder.modified")} (${folderData.modified_count})` }),
      el("button", { class: "filter-chip chip-add", "data-f-filter": "added", text: `${i18n.t("folder.added")} (${folderData.added_count})` }),
      el("button", { class: "filter-chip chip-del", "data-f-filter": "removed", text: `${i18n.t("folder.removed")} (${folderData.removed_count})` }),
      el("button", { class: "filter-chip", "data-f-filter": "identical", text: `${i18n.t("folder.identical")} (${folderData.identical_count})` }),
    ]),
  ]);
  container.appendChild(head);

  const table = el("table", { class: "folder-table" });
  const thead = el("thead", {}, [
    el("tr", {}, [
      el("th", { style: "width: 110px;", text: i18n.t("folder.status") }),
      el("th", { text: i18n.t("folder.path") }),
      el("th", { style: "width: 120px;", text: `A ${i18n.t("folder.size")}` }),
      el("th", { style: "width: 120px;", text: `B ${i18n.t("folder.size")}` }),
      el("th", { style: "width: 140px; text-align: right;", text: "" }),
    ]),
  ]);
  table.appendChild(thead);

  const tbody = el("tbody");
  const fmtBytes = (bytes) => {
    if (bytes === null || bytes === undefined) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  for (const item of folderData.items) {
    let badgeClass = "badge-same";
    let badgeText = i18n.t("folder.identical");
    if (item.status === "modified") {
      badgeClass = "badge-mod";
      badgeText = i18n.t("folder.modified");
    } else if (item.status === "added") {
      badgeClass = "badge-add";
      badgeText = i18n.t("folder.added");
    } else if (item.status === "removed") {
      badgeClass = "badge-del";
      badgeText = i18n.t("folder.removed");
    }

    const tr = el("tr", { class: `f-row f-row-${item.status}`, "data-status": item.status });
    tr.appendChild(el("td", {}, [el("span", { class: `folder-badge ${badgeClass}`, text: badgeText })]));
    tr.appendChild(el("td", { class: "f-rel-path", text: item.rel_path }));
    tr.appendChild(el("td", { text: fmtBytes(item.left_size) }));
    tr.appendChild(el("td", { text: fmtBytes(item.right_size) }));

    const actionTd = el("td", { style: "text-align: right;" });
    if (item.status === "modified" && item.left_path && item.right_path) {
      const btn = el("button", {
        class: "flat folder-diff-btn",
        type: "button",
        text: i18n.t("folder.compare"),
        onclick: () => openFilePairInNewTab(item.left_path, item.right_path),
      });
      actionTd.appendChild(btn);
      tr.addEventListener("dblclick", () => openFilePairInNewTab(item.left_path, item.right_path));
    }
    tr.appendChild(actionTd);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);

  for (const chip of head.querySelectorAll(".filter-chip")) {
    chip.addEventListener("click", () => {
      head.querySelectorAll(".filter-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      const filter = chip.dataset.fFilter;
      for (const row of tbody.querySelectorAll(".f-row")) {
        if (filter === "all" || row.dataset.status === filter) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      }
    });
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
  const saved = safeStorageGet(BOX_COLOR_KEY);
  applyBoxColor(saved);
  for (const item of $$("#box-color-menu [data-color]")) {
    item.addEventListener("click", () => {
      closeMenus();
      applyBoxColor(item.dataset.color);
      safeStorageSet(BOX_COLOR_KEY, item.dataset.color);
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

function pageImage(base, alt, eager = false) {
  const img = el("img", {
    "data-base": base,
    alt,
    loading: eager ? "eager" : "lazy",
  });
  img.addEventListener("load", () => {
    img.closest(".page-canvas")?.classList.remove("is-loading");
    img.classList.add("loaded");
  });
  img.addEventListener("error", () => {
    img.closest(".page-canvas")?.classList.remove("is-loading");
  });
  img.src = `${base}?dpi=${pageDpi()}`;
  return img;
}

let dpiTimer = 0;
function scheduleDpiUpdate() {
  clearTimeout(dpiTimer);
  dpiTimer = setTimeout(() => {
    const dpi = pageDpi();
    for (const img of $$("#page-view img[data-base]")) {
      const next = `${img.dataset.base}?dpi=${dpi}`;
      if (img.getAttribute("src") !== next) {
        img.closest(".page-canvas")?.classList.add("is-loading");
        img.src = next;
      }
    }
  }, 250);
}

function resolveZoom() {
  if (typeof state.zoom === "number") return state.zoom;
  const view = $("#page-view");
  if (!view.clientWidth) return state.zoomValue;
  const extent = pageExtent();
  // In xray mode, using cols = 1 with full window width stretches a single page across the whole wide screen.
  // Instead, size it comfortably (matching side-by-side page size or max 1.05 actual scale).
  const cols = 2;
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
  if (state.mode === "xray" && state.zoom === "width") {
    zoom = Math.min(zoom, 1.05);
  }
  if (state.zoom === "page") {
    const stickyHeader = $(".result-sticky-header");
    const top = $(".topbar").offsetHeight + (stickyHeader ? stickyHeader.offsetHeight : ($(".result-head") ? $(".result-head").offsetHeight : 0));
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
  closeSearch();
  applyKindFilter("all");
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
  if ($("#change-nav")) $("#change-nav").hidden = true;
  if ($("#top-diff-nav")) $("#top-diff-nav").hidden = true;
  if ($("#diff-minimap")) $("#diff-minimap").hidden = true;
  if ($("#folder-view")) $("#folder-view").hidden = true;
  if ($("#tab-folder")) $("#tab-folder").hidden = true;
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
if ($("#export-pdf")) {
  $("#export-pdf").addEventListener("click", (event) => {
    closeMenus();
    openExternal(event, $("#export-pdf").getAttribute("href"));
  });
}

/* ---------- wiring ---------- */
setupDropZones();
setupMinimap();
setupMenus();
function updateIntegrationUI(data) {
  const pill = $("#settings-integrate-pill");
  const toggleBtn = $("#settings-integrate-toggle");
  const pendingRow = $("#settings-pending-row");
  const pendingPath = $("#settings-pending-path");
  const legacyBtn = $("#integrate-menu");

  const installed = Boolean(data && data.installed);
  if (pill) {
    pill.dataset.installed = String(installed);
    pill.className = `pref-status-pill ${installed ? "installed" : "not-installed"}`;
    pill.textContent = i18n.t(installed ? "settings.integrate.statusInstalled" : "settings.integrate.statusNotInstalled");
  }
  if (toggleBtn) {
    toggleBtn.dataset.installed = String(installed);
    toggleBtn.className = installed ? "flat" : "suggested";
    toggleBtn.textContent = i18n.t(installed ? "menu.integrateRemove" : "menu.integrate");
  }
  if (pendingRow && pendingPath) {
    if (data && data.pending_name) {
      pendingRow.hidden = false;
      pendingPath.textContent = data.pending_name;
    } else {
      pendingRow.hidden = true;
      pendingPath.textContent = i18n.t("settings.integrate.noPending");
    }
  }
  if (legacyBtn) {
    legacyBtn.dataset.installed = String(installed);
    legacyBtn.textContent = i18n.t(installed ? "menu.integrateRemove" : "menu.integrate");
  }
}

async function toggleIntegration() {
  const pill = $("#settings-integrate-pill");
  const legacyBtn = $("#integrate-menu");
  const isInstalled = pill
    ? pill.dataset.installed === "true"
    : legacyBtn
      ? legacyBtn.dataset.installed === "true"
      : false;
  const action = isInstalled ? "uninstall" : "install";

  try {
    let result;
    if (desktop.available && window.pywebview && window.pywebview.api && window.pywebview.api.integrate) {
      result = await window.pywebview.api.integrate(action, i18n.lang);
    } else {
      const response = await fetch("/api/integrate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, language: i18n.lang }),
      });
      result = await response.json();
    }

    if (result && result.success) {
      updateIntegrationUI(result);
      showToast(i18n.t(result.installed ? "integrate.installed" : "integrate.removed"));
    } else {
      showToast((result && result.error) || i18n.t("error.generic"), true);
    }
  } catch (err) {
    showToast(err.message || i18n.t("error.generic"), true);
  }
}

async function clearPendingSelection() {
  try {
    let result;
    if (desktop.available && window.pywebview && window.pywebview.api && window.pywebview.api.integrate) {
      result = await window.pywebview.api.integrate("clear_pending", i18n.lang);
    } else {
      const response = await fetch("/api/integrate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "clear_pending", language: i18n.lang }),
      });
      result = await response.json();
    }
    if (result && result.success) {
      updateIntegrationUI(result);
      showToast(i18n.t("settings.integrate.clearPending"));
    }
  } catch (err) {
    showToast(err.message || i18n.t("error.generic"), true);
  }
}

function updateIntegrationState(installed) {
  updateIntegrationUI({ installed });
}

async function loadIntegrationStatus() {
  try {
    let data;
    if (desktop.available && window.pywebview && window.pywebview.api && window.pywebview.api.get_integrate_status) {
      data = await window.pywebview.api.get_integrate_status();
    } else {
      const response = await fetch("/api/integrate/status");
      if (!response.ok) return;
      data = await response.json();
    }
    updateIntegrationUI(data);
  } catch (_) {}
}

function loadStoredPreferences() {
  const prefSpace = safeStorageGet("diffanydoc.pref.space");
  const prefCase = safeStorageGet("diffanydoc.pref.case");
  const prefFormat = safeStorageGet("diffanydoc.pref.format");

  if (prefSpace !== null) {
    const val = prefSpace === "true";
    if ($("#opt-space")) $("#opt-space").checked = val;
    if ($("#settings-default-space")) $("#settings-default-space").checked = val;
  }
  if (prefCase !== null) {
    const val = prefCase === "true";
    if ($("#opt-case")) $("#opt-case").checked = val;
    if ($("#settings-default-case")) $("#settings-default-case").checked = val;
  }
  if (prefFormat !== null) {
    const val = prefFormat === "true";
    if ($("#opt-format")) $("#opt-format").checked = val;
    if ($("#settings-default-format")) $("#settings-default-format").checked = val;
  }
}

function setupPreferences() {
  try {
    loadStoredPreferences();

    const bindPref = (settingId, optId, key) => {
      const settingEl = $(`#${settingId}`);
      const optEl = $(`#${optId}`);
      if (settingEl) {
        settingEl.addEventListener("change", (e) => {
          const val = e.target.checked;
          safeStorageSet(key, String(val));
          if (optEl) optEl.checked = val;
        });
      }
      if (optEl) {
        optEl.addEventListener("change", (e) => {
          const val = e.target.checked;
          safeStorageSet(key, String(val));
          if (settingEl) settingEl.checked = val;
        });
      }
    };

    bindPref("settings-default-space", "opt-space", "diffanydoc.pref.space");
    bindPref("settings-default-case", "opt-case", "diffanydoc.pref.case");
    bindPref("settings-default-format", "opt-format", "diffanydoc.pref.format");
  } catch (_) {}
}

function setupAdvancedExpander() {
  try {
    const btn = $("#advanced-toggle-btn");
    const panel = $("#advanced-panel");
    if (!btn || !panel) return;
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const isExpanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!isExpanded));
      panel.hidden = isExpanded;
    });
  } catch (_) {}
}

/* Action buttons */
const compareBtn = $("#compare");
if (compareBtn) {
  compareBtn.addEventListener("click", (e) => {
    e.preventDefault();
    runComparison();
  });
}
const restartBtn = $("#restart");
if (restartBtn) restartBtn.addEventListener("click", reset);
if ($("#new-compare-btn")) $("#new-compare-btn").addEventListener("click", reset);
if ($("#add-tab")) $("#add-tab").addEventListener("click", createNewSessionTab);
if ($("#new-tab-btn")) $("#new-tab-btn").addEventListener("click", createNewSessionTab);
if ($("#new-tab-menu")) $("#new-tab-menu").addEventListener("click", createNewSessionTab);
if ($("#reload")) $("#reload").addEventListener("click", reloadComparison);
if ($("#copy-all-to-right")) $("#copy-all-to-right").addEventListener("click", () => mergeAllToSide("left"));
if ($("#copy-all-to-left")) $("#copy-all-to-left").addEventListener("click", () => mergeAllToSide("right"));
if ($("#copy-changes")) $("#copy-changes").addEventListener("click", () => copyView("changes"));
if ($("#copy-left")) $("#copy-left").addEventListener("click", () => copyView("left"));
if ($("#copy-right")) $("#copy-right").addEventListener("click", () => copyView("right"));
if ($("#copy-both")) $("#copy-both").addEventListener("click", () => copyView("both"));
if ($("#download-left")) $("#download-left").addEventListener("click", () => downloadSideDocument("left"));
if ($("#download-right")) $("#download-right").addEventListener("click", () => downloadSideDocument("right"));

setupDialogs();
setupAdvancedExpander();
setupPreferences();
loadTheme();

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
setupSearch();

const statsBtn = $("#stats");
if (statsBtn) {
  statsBtn.addEventListener("click", openStatsDetails);
  statsBtn.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openStatsDetails();
    }
  });
}

if ($("#prev-change")) $("#prev-change").addEventListener("click", () => gotoChange(-1));
if ($("#next-change")) $("#next-change").addEventListener("click", () => gotoChange(1));
if ($("#top-prev-change")) $("#top-prev-change").addEventListener("click", () => gotoChange(-1));
if ($("#top-next-change")) $("#top-next-change").addEventListener("click", () => gotoChange(1));

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

  if ((event.ctrlKey || event.metaKey) && event.key === ",") {
    event.preventDefault();
    openSettings();
    return;
  }

  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "o" &&
    !$("#upload-view").hidden
  ) {
    event.preventDefault();
    const empty = !hasFile("left") ? "left" : !hasFile("right") ? "right" : "left";
    chooseFile(empty);
    return;
  }

  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "f" &&
    !$("#result-view").hidden
  ) {
    event.preventDefault();
    openSearch();
    return;
  }

  if (event.key === "Escape") {
    const searchBar = $("#search-bar");
    if (searchBar && !searchBar.hidden) {
      closeSearch();
      return;
    }
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

  // Navigation shortcuts with Alt (Alt+Down, Alt+Up) or F7 (F7, Shift+F7)
  if (state.comparison && !$("#result-view").hidden) {
    if (event.key === "F7") {
      event.preventDefault();
      gotoChange(event.shiftKey ? -1 : 1);
      return;
    }
    if (event.altKey && !event.ctrlKey && !event.metaKey) {
      if (event.key === "ArrowDown" || event.key === "Down") {
        event.preventDefault();
        gotoChange(1);
        return;
      }
      if (event.key === "ArrowUp" || event.key === "Up") {
        event.preventDefault();
        gotoChange(-1);
        return;
      }
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
  await loadIntegrationStatus();
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
