# Design system

Headcount Desk is a planning instrument. It should feel **precise, calm and dense**: closer to a well-made spreadsheet than to a marketing page. This file is the spec. `app/static/app.css` implements it, and `/styleguide` shows every piece in both themes.

## Principles

1. **The number is the hero.** One answer per page, set large, in tabular figures. Everything else explains it.
2. **Ink, paper and one accent.** A cool neutral scale does almost all the work. A single teal accent marks what you can act on. Green, amber and red mean status and nothing else, and always come with an icon and a word.
3. **Dense, not cramped.** Rows are 40px. Whitespace separates groups, not every element. A 1440px screen should show a whole decision without scrolling.
4. **Never lose your place.** Detail opens in a side drawer. Filters and sort live in the URL. Back always works.
5. **Show the work.** Every number links to its rows. Loading, empty and error states are designed.
6. **Quiet motion.** 120 to 200ms, ease-out, only to show where something came from. None at all if the system asks for reduced motion.
7. **Dark is designed, not inverted.** Dark surfaces get lighter as they rise; borders do the separating; the accent is lighter and less saturated.
8. **If a sentence explains a chart, fix the chart.** Labels sit on the marks. Method notes stay one click away under "Show the math."
9. **Say a repeated fact once.** It moves up a level: freshness to the top bar, org facts above a queue, the fix above a group of rows.
10. **A click changes the view in place.** Filters, sorting and chart choices swap the content and keep the URL in sync.

## Tokens

All tokens are CSS custom properties. Light is the default; `[data-theme="dark"]` swaps them. The attribute can sit on any element, which is how the styleguide shows both themes side by side.

### Color

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f4f5f7` | `#0c0f13` | Page |
| `--surface` | `#ffffff` | `#14181e` | Cards, drawer, menus |
| `--surface-2` | `#f8f9fa` | `#1a1f27` | Table headers, insets |
| `--surface-3` | `#eef0f3` | `#222833` | Hover, pressed |
| `--border` | `#e2e5ea` | `#262c37` | Hairlines |
| `--border-strong` | `#c9ced6` | `#3a4250` | Inputs, emphasis |
| `--text` | `#12161c` | `#e9edf2` | Primary ink |
| `--muted` | `#5a6472` | `#9aa5b4` | Secondary ink (AA on every surface) |
| `--accent` | `#0b6b73` | `#4fc3cb` | Links, primary buttons, the usable-open segment |
| `--accent-ink` | `#085158` | `#7fd8de` | Accent text |
| `--accent-soft` | `#e2f2f3` | `#12333a` | Selected, focus halo |
| `--on-accent` | `#ffffff` | `#06282c` | Text on the accent |
| `--good` / `--good-soft` | `#1a7a3c` / `#e6f4ea` | `#5fce86` / `#12301e` | Passed, filled, under budget |
| `--warn` / `--warn-soft` | `#9a5a00` / `#fdf2dc` | `#f0b451` / `#3a2a0c` | Needs a look, watch |
| `--bad` / `--bad-soft` | `#b42318` / `#fdecea` | `#ff8a80` / `#3d1714` | Failed, rejected, over budget |

Chart segments use ink steps for what is spent (`--seg-filled`, `--seg-committed`, `--seg-reserve`, `--seg-negative`) and the accent for what is left (`--seg-usable`). The Committed and Reserve steps are far enough apart to separate in both themes, for all common kinds of color vision. Identity never depends on color alone: every segment has a label and a value.

### Type

One family, Inter (self-hosted variable font), with tabular figures and a slashed zero for data. Codes and IDs use the system monospace stack.

| Token | Size / line | Weight | Use |
|---|---|---|---|
| `--t-hero` | 64 / 1 | 650 | The answer |
| `--t-h1` | 22 / 1.25 | 650 | Page question |
| `--t-h2` | 15 / 1.3 | 600 | Card titles |
| `--t-body` | 14 / 1.5 | 400 | Everything else |
| `--t-small` | 12.5 / 1.45 | 400 | Meta, table headers |
| `--t-micro` | 11 / 1.3 | 600, +0.06em caps | Eyebrows |

### Space, radius, elevation, motion

- **Space:** a 4px base. `--s1` 4, `--s2` 8, `--s3` 12, `--s4` 16, `--s5` 24, `--s6` 32, `--s7` 48.
- **Radius:** `--r-sm` 4 (chips, inputs), `--r` 8 (cards, buttons), `--r-lg` 12 (drawer, dialogs).
- **Elevation:** `--e1` hairline shadow for cards, `--e2` for menus, `--e3` for the drawer and palette. In dark, elevation is mostly a lighter surface plus a border.
- **Banner:** `--banner` 29px, the demo strip above the shell.
- **Motion:** `--fast` 120ms, `--med` 200ms, `cubic-bezier(.2, .8, .2, 1)`. Wrapped in `prefers-reduced-motion`.

## Layout

- **Desktop (900px and up):** a 216px sidebar with the nav, a 52px top bar (tour, search, freshness, theme, role), and a content column capped at 1180px.
- **Phone (under 900px):** the sidebar becomes a bottom tab bar with four destinations and a "More" sheet. Tables collapse to cards. The drawer is full width.
- Content uses container queries, so a table collapses the same way inside the drawer as it does on a phone.

## Components

| Component | Spec |
|---|---|
| **Page head** | The page's question as `h1`, page-specific context if any, actions on the right. Freshness lives in the top bar chip. |
| **Show the math** | A closed control with numbered steps, in place of a paragraph. |
| **Stat / hero** | Eyebrow, hero number, one caption sentence. The number is a link. |
| **Seat map** | One square per unfilled seat, grouped by kind. Bucket buttons highlight a kind and rank the orgs below in place. |
| **Variance bar** | Percent of budget on a 95 to 105 scale, centered on 100%. Under runs left, over runs right. The number beside it stays exact when a value is past the end of the scale. |
| **Stacked bar** | One total split into labeled parts: run-rate, committed, what is left. |
| **Ranked bars** | A sorted list of thin bars with the value at the tip. Used when magnitude is the point, as with exception types. |
| **Sparkline** | A small line with its last point marked. Hover or focus gives the range. |
| **Fan chart** | Daily history into a likely range at quarter end. Drawn in the browser because the what-if sliders redraw it. Nothing a slider does is saved. |
| **Pipeline** | Stages in order, each as wide as its count, each a filter. |
| **Room gauge** | Only the room to grow is drawn, because this year's headcount would swamp it. Submitted, this plan, and what is left. |
| **Check grid** | Checks by day. A bad night is a column, a flaky check is a row. Cells open that run. |
| **Treemap** | Two levels below an org. Area is approved seats, shading is budget position. Click to zoom. The table stays the default view. |
| **Chart tooltip** | One shared tooltip on hover and focus. It adds detail and never holds the only copy of a value. |
| **Card** | Surface, 1px border, `--r`, `--e1`. Optional header row with title and actions. |
| **Table** | 40px rows, sticky header, right-aligned tabular numbers, sortable headers (`aria-sort`) that sort in place, row actions revealed on hover or focus, pagination footer, CSV link. Collapses to cards in a narrow container, or to name and the key numbers when marked compact. |
| **Chip** | 20px tall pill. Neutral, accent, good, warn, bad. Always an icon from the one SVG set plus a word. Shown only when it says something: no "fine" flags on every row. |
| **Button** | 32px. Primary (accent), default (bordered), quiet (text). 28px small size. |
| **Drawer** | 520px from the right, `--e3`, focus moves in and returns on close, Esc closes, deep-linkable through the URL hash. |
| **Command palette** | ⌘K or `/`. One input, grouped results (go to, people and positions, orgs, actions), arrow keys and Enter. |
| **Toast** | Bottom center, 6 seconds, optional Undo. `aria-live="polite"`. |
| **Stepper and timeline** | Progress through a workflow, then the audit trail that proves it. |
| **Banner** | A one-sentence verdict with an icon: good, warn or bad. |
| **Empty and error states** | A sentence that says what is true, and one next action. |
| **Skeleton** | Grey bars in the shape of what is loading. No spinners. |

## Accessibility

- Contrast is AA or better for all text in both themes.
- Everything works by keyboard. Focus is always visible (2px accent ring).
- Status is never color alone. Charts have text equivalents.
- Checked with axe-core in the end-to-end tests: zero serious or critical violations on every page.
