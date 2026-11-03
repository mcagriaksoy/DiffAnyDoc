# DiffAnyDoc — Design System

This document is binding: when adding a screen or component, follow the rules
here. It exists for two reasons:

1. **Prevent AI slop** — instead of making the average "slightly nicer" decision
   on every screen, pick from a ready-made widget vocabulary.
2. **Feel equally professional on Windows and Linux** — the shell matches the
   platform, the content is the same everywhere.

Reference: GNOME HIG / libadwaita (structure, sizing, colour) + diff tools
(Beyond Compare, GitHub diff) — for the content area.

---

## 1. Principles

- **Function, not decoration.** An element is coloured only because it carries
  information.
- **One accent.** Never more than one highlight colour per screen; the accent
  comes from the system.
- **One scale.** Spacing, radius and type sizes are picked from fixed lists.
- **One chrome.** When there is a native title bar, there is no second title bar
  inside the app.
- **Motion carries meaning.** Animation only explains a state change; it never
  draws attention.

## 2. Sizing

| Token | Value | Use |
|---|---|---|
| `--space-1 … --space-5` | 6 / 12 / 18 / 24 / 36 px | All spacing. No intermediate values. |
| `--control-height` | 34 px | Buttons, inputs, dropdowns |
| `--radius-sm` | 6 px | Buttons, tabs, inputs |
| `--radius-md` | 9 px | Cards, drop areas |
| `--radius-lg` | 12 px | Panels, popovers |
| Fully round (999px) | switches/toggles only | Never used elsewhere |

Touch targets never go below 28 px.

## 3. Typography

| Role | Size | Weight |
|---|---|---|
| Body / chrome | 14.5 px (≈11 pt) | 400 |
| Caption, meta | 12 px (≈9 pt) | 400, dim colour |
| Section title | 20 px (≈15 pt) | 700 |
| Diff content | 12.5 px monospace | 400 |

- Font: `system-ui` → Cantarell/Ubuntu on Linux, Segoe UI Variable on Windows,
  SF Pro on macOS. The app does not ship or force its own font.
- No negative `letter-spacing`. At most 3 type sizes and 1 bold title per screen.

## 4. Colour

Adwaita naming is used; changing the theme changes tokens, not code.

| Token | Light | Dark |
|---|---|---|
| `--window-bg-color` | `#fafafb` | `#1d1d20` |
| `--view-bg-color` | `#ffffff` | `#26262a` |
| `--headerbar-bg-color` | `#ffffff` | `#303034` |
| `--popover-bg-color` | `#ffffff` | `#38383c` |
| `--border-color` | `rgba(0,0,0,.12)` | `rgba(255,255,255,.12)` |
| `--text-color` | `#1d1d20` | `#ffffff` |
| `--dim-label-color` | `#6b7280` | `#b0b0b6` |
| `--accent-bg-color` | system / `#3584e4` | system / `#78aeed` |
| `--success-color` | `#1c7d4d` | `#7ee2a8` |
| `--warning-color` | `#8a6100` | `#ffd479` |
| `--error-color` | `#b3261e` | `#ff9d9d` |

Rules:

- Semantic colour only for diffs and real status messages. **Stats with a zero
  value are not coloured.**
- Coloured text and coloured background are not used together (no green on
  green). Text stays neutral, background at 10–14% alpha, a 2 px marker on the
  left edge.
- Colour never carries meaning alone: `+`, `−`, `~` signs always accompany it.
- Contrast at least 4.5:1.

## 5. Depth and motion

- Rule: **border OR shadow.** Both together only in popovers/menus (shadow +
  thin ring).
- Surfaces are flat; no lift, scale or growing shadow on hover.
- Hover = background tint; pressed = one tint darker.
- Transitions 100–150 ms, only `background-color`, `opacity`, `left`.
  `prefers-reduced-motion` is supported.

## 6. Icons

- Symbolic, single colour, `currentColor`, 16 px (chrome) / 24 px (drop area) /
  48 px (empty state).
- Stroke 1.5 px. No emoji, multi-colour illustration or gradient icons.
- The app icon appears only in the launcher and in About.

## 7. Components

### Buttons
| Kind | Appearance | Rule |
|---|---|---|
| `suggested` | accent fill, white text, 6 px radius | **At most 1** per screen |
| `flat` | transparent, grey tint on hover | Default; toolbars and icon buttons |
| `destructive` | error-colour text | Only for irreversible actions |

Order: `flat` → `suggested`. Reversed hierarchy (filled buttons everywhere) is a
slop signal.

### Switch / checkbox
- A setting that takes effect immediately → **switch**.
- A form choice that parameterises the comparison → **checkbox**.

### Menu
- At most 2 levels. 34 px rows, 12 px radius, shadow + thin ring.
- Non-destructive actions are collected in a single "⋯" menu in the top right.

### Empty state (AdwStatusPage)
`icon (48 px) → title (20 px) → one-sentence description → one action`.
No marketing copy, slogan or "hero" headline.

### Diff rows
- Row background and inline highlight work together; both come from the same
  colour family, one at 10% and the other at 20% alpha.
- No background for unchanged lines.
- Line numbers and page labels are dim and not selectable.
- Table rows render their cells in a thin grid inside the row; a changed cell
  gets a 2 px warning-colour underline, its words the usual inline highlight.
- Automatic numbering ("4.2.") is dim: it is shown, not compared.

### Page overlays
- Changed words: filled box in the diff colour. The line a changed word sits
  on: 1 px dashed outline only (context, not a second highlight).
- Visual (pixel) regions: 2 px dashed **accent** outline, never filled, so they
  read as "look here" on top of the word boxes.
- The Overlay image is content, not chrome: it always uses the fixed pair
  red `#e01b24` (only in A) / green `#26a269` (only in B) on grey, in both
  themes, with a legend above it.
- Boxes are buttons: clicking one opens the line in the text view.

## 8. Platform alignment

| | GNOME / Linux | Windows | macOS |
|---|---|---|---|
| Font | Cantarell / system | Segoe UI Variable | SF Pro |
| Window bar | GTK native | native | native |
| Accent source | `gsettings accent-color` | DWM `ColorizationColor` | fixed (for now) |
| Corner radii | 6 / 9 / 12 | same | same |
| Dark theme | `prefers-color-scheme` | system | system |

Chrome (title bar, dialogs, file picker) **belongs to the platform**; content
(diff view, stats, panels) is the same everywhere. GNOME-specific window
controls are never imitated inside the webview.

## 9. Adwaita widget mapping

| Our screen | libadwaita |
|---|---|
| Top bar | `AdwHeaderBar` |
| View tabs | `AdwViewSwitcher` |
| Empty state | `AdwStatusPage` |
| Language / options | `AdwPreferencesPage`, `AdwComboRow` |
| Immediate setting | `AdwSwitchRow` |
| Error | `AdwBanner` |
| Transient message | `AdwToast` |
| About / version | `AdwAboutDialog` (summary in the menu) |

## 10. Forbidden list (AI slop signals)

1. Glassmorphism, backdrop-blur title bars
2. Wrapping every piece of text in a coloured pill/chip
3. Border + shadow + gradient on the same element
4. `translateY`/`scale` "lift" effects on hover
5. Centred landing-page hero and slogan
6. 4+ different radii on the same screen
7. Emoji or multi-colour icons
8. Colouring zero-value stats
9. Negative letter-spacing, 27 px giant headlines
10. Showing the same information twice (version, file name)

## 11. Pre-delivery check

1. Radius variety ≤ 2
2. Border and shadow not on the same element
3. Every coloured item carries meaning
4. All spacing is a multiple of 6
5. No motion on hover
6. Type sizes ≤ 3
7. One accent button
8. Contrast ≥ 4.5:1
9. Every flow is keyboard-completable
10. No marketing copy on the screen

## 12. Code

Tokens are defined in the `:root` block at the top of
`src/diffanydoc/web/static/app.css`. If a new colour or size is needed, add it to
this document first as a token. The accent colour comes from
`GET /api/system/theme` and is written to the `--accent-bg-color` variable.
