# Clean Muzik: design system

**Direction: Broadcast badge.** A varsity sports-broadcast console. A drenched crest-navy badge rail
holds the brand at jersey-patch scale down the left of the canvas; the work runs flush left in an
unbounded column beside it, headed by a block-capital view title, a teal rule across the slack and a
scoreboard of set figures flush right; and the Track being downloaded is not a card but a broadcast
lower third pinned across the bottom of the work column.

The equaliser horizon the mock shows was built and then removed (2026-09-16): it read as clutter.
Section 6 records the removal; do not bring it back.

This file is the contract. Where it and a mock disagree, this file wins.

## Visual truth

Open the winning mock in a browser before writing CSS:

- `/tmp/claude-1000/-home-armand-github-muziktest/2787d639-d8ee-42da-bf09-3d20cd987e7a/scratchpad/concepts/broadcast-badge/mock.html`
- Shots: `.../broadcast-badge/desktop.png`, `desktop-viewport.png`, `mobile.png`, `mobile-viewport.png`
- Runner-up mocks, referenced only where a graft below names them:
  - `.../concepts/mixing-desk/mock.html` (segmented meters, written paths, panel discipline)
  - `.../concepts/poster/mock.html` (the four-rulings legend, the mobile Run order)

Five corrections to the mock are mandatory and are specified below: (1) Bungee is restricted, (2)
machine strings move to a mono stack, (3) the horizon is shorter (moot: removed, section 6), (4) the shell mounts exactly one
canvas (likewise moot), (5) the invented QUEUED rows are dropped.

---

## 1. Tokens

All tokens live in `static/styles/tokens.css` (Foundation lane). Nothing outside that file defines a
raw colour, size or duration. Hex values are informational: OKLCH is authoritative.

### 1.1 Colour

Dark only. Strategy is Restrained plus one Committed surface: the badge rail is drenched in crest
navy, everything else is a neutral navy-tinted dark with a single teal accent family. Amber and red
are semantic state, never decoration. Nothing in the UI is set below full opacity; there is no muted
ink anywhere.

| Token | OKLCH | Hex | Role |
|---|---|---|---|
| `--bg` | `oklch(17.5% 0.022 258)` | `#0a111a` | page ground, work column |
| `--surface` | `oklch(21.5% 0.026 254)` | `#111a25` | plates: tag record, open review row, witness block, appendix |
| `--surface-2` | `oklch(25.5% 0.028 252)` | `#192430` | inputs, selects, testimony panels, inline decision panels |
| `--plate-navy` | `oklch(24.0% 0.060 260)` | `#0d1e3b` | the badge rail, the lower third, and the ink colour on teal/amber fills |
| `--line` | `oklch(34.0% 0.030 250)` | `#2c3947` | 2px control borders, keyline buttons |
| `--line-soft` | `oklch(28.0% 0.026 250)` | `#1c2733` | 1px row hairlines |
| `--ink` | `oklch(96.5% 0.008 235)` | `#eff4f8` | all primary text. 17.16:1 on `--bg` |
| `--ink-2` | `oklch(85.5% 0.016 230)` | `#c5d2d8` | labels, captions, ledes, secondary data. 12.24:1 on `--bg`. A real colour, never `opacity` on `--ink` |
| `--teal-900` | `oklch(30.0% 0.055 205)` | `#00353b` | cover placeholder ground, meter track |
| `--teal-700` | `oklch(43.0% 0.070 210)` | `#0e5a65` | the crest's sampled teal. Structural rules, rail edge |
| `--teal-500` | `oklch(62.0% 0.100 200)` | `#1c989e` | hover borders. Decoration and large text only |
| `--teal-300` | `oklch(79.0% 0.105 196)` | `#5acfd0` | accent ink, primary fill, active nav fill, focus ring. 10.23:1 on `--bg`; `--plate-navy` on it 8.90:1 |
| `--amber` | `oklch(81.5% 0.140 80)` | `#f2b74a` | review-bound only: queued figure, Review chip, reason lines, review badge. 10.54:1 on `--bg`; `--plate-navy` on it 9.18:1 |
| `--red` | `oklch(66.5% 0.185 26)` | `#f05b54` | failed and refused only: state word, error lines. 5.71:1 on `--bg` |

Semantic aliases (use these in component CSS, not the raw ramp):

```
--accent: var(--teal-300);
--accent-ink: var(--plate-navy);   /* text that sits ON teal-300 or amber */
--focus: var(--teal-300);
--rule: var(--teal-700);           /* 3px structural rules */
--state-ok: var(--teal-300);
--state-review: var(--amber);
--state-bad: var(--red);
```

Rules, enforced in review:

- `--teal-300` and `--amber` are ink-or-fill. `--plate-navy` sits on them; white never does.
- `--teal-500` never carries text under 18px.
- `--red` is never a text background (`--ink` on it is 3.01:1). Failure copy sits on `--bg` or `--surface`.
- One accent family across all three views. No second hue.
- No `#000`. No neon glow, no `filter: blur`, no `box-shadow` used as a halo.

### 1.2 Type

Two families on a real contrast axis, plus a system mono for machine strings.

- **Display: Bungee** (OFL). Squared block capitals, effectively the crest's own lettering.
- **UI: Archivo** (OFL, variable 400/500/600/700). Grotesque, tabular figures, wide apertures.
- **Mono: system stack**, zero download: `ui-monospace, "SF Mono", "Cascadia Mono", "DejaVu Sans Mono", Menlo, monospace`.

```
--font-display: "Bungee", "Archivo Black", "Arial Black", system-ui, sans-serif;
--font-ui:      "Archivo", system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
--font-mono:    ui-monospace, "SF Mono", "Cascadia Mono", "DejaVu Sans Mono", Menlo, monospace;
```

`body { font-family: var(--font-ui); font-variant-numeric: tabular-nums; }`

**Bungee is restricted.** This is the correction to the mock, and it is not negotiable: the product
register bans display type in UI labels, buttons and data. Bungee appears ONLY on:

1. the nav items in the rail / mobile tabs,
2. the view title (`h1`),
3. set figures (the scoreboard, the run summary numerals, the review queue numbers),
4. the on-air state word in the rail,
5. the lower third's percentage numeral,
6. section headings inside a view (the testimony heading, "How this works"),
7. the Review empty-state headline.

Everything else is Archivo: every field label, button label, chip, data value, table cell, paragraph,
option name, error message. Chips are Archivo 700 uppercase, not Bungee.

**Mono is for machine strings only** (graft from the mixing-desk direction): Source URLs, file paths,
`output_path`, download speed, elapsed time, the playlist file path, manifest entries. Never for
prose, labels or titles.

Fixed px scale, no fluid clamps (product register). Desktop is `>= 901px`, mobile is `<= 900px`.

| Token | Desktop | Mobile | Face / weight | Where |
|---|---|---|---|---|
| `--t-display` | 64px / .86 / -0.005em | 38px / .9 | Bungee | view title `h1` |
| `--t-empty` | 44px / .95 | 28px | Bungee | Review empty-state headline |
| `--t-figure` | 48px / .9 | 34px | Bungee | scoreboard figures, summary numerals |
| `--t-pct` | 48px / .9 | 32px | Bungee | lower-third percentage |
| `--t-state` | 30px / 1 | 24px | Bungee | on-air state word |
| `--t-head2` | 28px / 1.05 | 22px | Bungee | testimony heading, "How this works" |
| `--t-nav` | 24px / 1 | 15px | Bungee | nav items |
| `--t-plate` | 22px | 19px | Archivo 700 | format plate name |
| `--t-title` | 19px / 1.3 | 17px | Archivo 600 | Track title, review item title, tag value |
| `--t-lede` | 17px / 1.5 | 16px | Archivo 400 | view sub, witness quote |
| `--t-body` | 16px / 1.55 | 15px | Archivo 400 | prose, reasons, notes |
| `--t-btn` | 14px / 1, 0.10em | 14px | Archivo 700 caps | every button label |
| `--t-data` | 14px / 1.4 | 13.5px | mono 400 | URLs, paths, speed, elapsed |
| `--t-label` | 12px / 1, 0.18em | 11.5px | Archivo 500 caps | field labels, scoreboard legends |
| `--t-chip` | 11.5px / 1, 0.14em | 11px | Archivo 700 caps | state chips |

Floor: nothing below 11.5px. Prose capped at 62ch, settings columns at 58ch each.
`text-wrap: balance` on `h1`/`h2`; `text-wrap: pretty` on paragraphs.

Uppercase tracked type exists here only as field labels, scoreboard legends and chips. There is not
one kicker above one heading anywhere in this design, and adding one is a review failure.

### 1.3 Spacing

4px base. Use the tokens; do not write raw px in view CSS.

```
--sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px; --sp-5: 24px;
--sp-6: 32px; --sp-7: 40px; --sp-8: 48px; --sp-9: 64px; --sp-10: 88px;
```

Layout dimensions:

```
--rail-w:     360px;   /* desktop only */
--gutter:     48px;    /* work column left/right padding; 20px on mobile */
--work-top:   40px;    /* work column top padding; 24px on mobile */
--lt-h:       76px;    /* lower third height; 64px on mobile */
--row-h:      56px;    /* tracklist / review head minimum row height */
--ctl-h:      52px;    /* input, select and button height; 48px on mobile */
--tap:        44px;    /* minimum touch target */
```

### 1.4 Radii and borders

**Radius is 0 everywhere. No exceptions, including the switch knob** (a square knob in a square track
reads as a hardware slide switch and keeps the shape lock intact). Do not introduce a radius token.

```
--bw-hair:   1px;  /* var(--line-soft): row separation, one bottom border per row, never top+bottom */
--bw-ctl:    2px;  /* var(--line): inputs, selects, keyline buttons, selected plates */
--bw-struct: 3px;  /* var(--teal-700): head rule, rail edge, decision bar, testimony rule */
```

Elevation is a hairline and a change of ground, never a shadow. There are no drop shadows in this
design.

### 1.5 Z-index

Semantic scale, in `tokens.css`. Never write a raw z-index.

```
--z-content:  1;   /* everything in the work column */
--z-rail:     10;  /* the badge rail / mobile masthead */
--z-lower:    20;  /* the lower third */
--z-sticky:   30;  /* mobile nav tabs when stuck */
```

There are no modals, so there is no modal layer. If you find yourself needing one, you have taken a
wrong turn: Manual and Hint open inline.

### 1.6 Motion

```
--ease-quart: cubic-bezier(.25, 1, .5, 1);
--ease-expo:  cubic-bezier(.16, 1, .3, 1);
--d-press:    120ms;   /* :active, colour shifts */
--d-state:    140ms;   /* lamp and state-word crossfade */
--d-arrive:   220ms;   /* a Track row arriving */
--d-open:     260ms;   /* review row expand */
--d-clear:    320ms;   /* a ruled row leaving; matches decide()'s existing timeout */
```

Nothing over 320ms. No page-load choreography: the app loads
into a task.

---

## 2. Shell

Files: `static/index.html`, `static/styles/shell.css`, `static/app.js` (Foundation lane only).

### 2.1 Markup

`index.html` keeps its module bootstrap and the `?mock=1` gate exactly as it is today. The body
becomes:

```html
<div class="shell">
  <header class="rail">
    <a class="brand" href="#/run">
      <span class="crest">
        <img class="crest-mark" src="./assets/crest-white-480.png" alt="Clean Muzik"
             width="847" height="817">
      </span>
    </a>
    <p class="strap">Source in, tagged Tracks out</p>
    <nav class="nav" aria-label="Views">
      <a href="#/run"      data-route="run">Run</a>
      <a href="#/review"   data-route="review">Review <span class="badge" id="review-badge" hidden></span></a>
      <a href="#/settings" data-route="settings">Settings</a>
    </nav>
    <div class="onair">
      <span class="lamp" id="run-lamp" aria-hidden="true"></span>
      <span class="onair-word" id="run-state">Idle</span>
      <span class="onair-source" id="run-source"></span>
    </div>
  </header>

  <main id="view" class="work"></main>

  <div class="lower-third" id="now-downloading" hidden>
    <i class="lt-meter" aria-hidden="true"></i>
    <span class="lt-cap">Now downloading</span>
    <span class="lt-title"></span>
    <span class="lt-speed"></span>
    <span class="lt-pct"><b>0</b><i>%</i></span>
  </div>
</div>
```

`#review-badge` and `#run-lamp` keep their ids: `setBadge` and `setLamp` in `app.js` are unchanged.
Delete `logo.png` from the UI (keep the file); the favicon becomes `./assets/crest-teal-480.png`.

### 2.2 Grid

Desktop (`>= 901px`):

```css
.shell {
  display: grid;
  grid-template-columns: var(--rail-w) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr) auto;
  height: 100dvh;
}
.rail    { grid-area: 1 / 1 / 3 / 2; z-index: var(--z-rail); }
.work    { grid-area: 1 / 2; overflow-y: auto; overscroll-behavior: contain;
           padding: var(--work-top) var(--gutter) var(--sp-8); }
.lower-third { grid-area: 2 / 2; z-index: var(--z-lower); }
```

The work column is the scroll container, and it is the ONLY scroll container in the app. `body` does
not scroll (`overflow: hidden` on `html, body`). **No view CSS may set `overflow` on any of its own
containers**: a view that does will double-scroll the tracklist. If a view needs a scrolling region,
report it as a finding instead.

The lower third is a real grid row, not an overlay, so it never covers the work column's text. Every
string sits on `--bg`, `--surface`, `--surface-2` or `--plate-navy`.

Mobile (`<= 900px`):

```css
.shell { grid-template-columns: minmax(0, 1fr);
         grid-template-rows: auto minmax(0, 1fr) auto; }
.rail    { grid-area: 1 / 1; }
.work    { grid-area: 2 / 1; padding: var(--work-top) var(--gutter) var(--sp-7); }
.lower-third { grid-area: 3 / 1; }
```

### 2.3 The badge rail (desktop)

360px wide, `background: var(--plate-navy)`, `border-right: var(--bw-struct) solid var(--teal-700)`,
`display: grid; grid-template-rows: auto auto auto 1fr auto;` padding `var(--sp-7) var(--sp-6)`.

1. **Crest**, 240px wide, top of the rail. See section 4.
2. **Strap**, `--t-label`, `--ink-2`, `Source in, tagged Tracks out`, under a `--bw-ctl` `--teal-700`
   top rule with `--sp-5` above and below.
3. **Nav**, stacked full-bleed rows (negative margin to the rail's padding edges), `--t-nav` Bungee,
   `--ink`, 56px tall, `padding-inline: var(--sp-5)`. The active row (`[aria-current="page"]`) is a
   solid `--teal-300` plate with `--accent-ink` type. The Review row carries `#review-badge` right
   aligned as an amber Bungee figure at 24px (it stays `hidden` at zero).
4. **Empty navy.** The `1fr` row is intentional. It is the composition, not a gap. Do not fill it.
5. **On-air block**, pinned bottom: a 14px square lamp, the state word (`--t-state` Bungee), and the
   Source URL under it in `--font-mono` at `--t-data`, `--ink-2`, truncated with
   `overflow-wrap: anywhere` to two lines max.

State colours on the on-air block: `idle` lamp `--line`, word `--ink-2`; `running` lamp and word
`--teal-300`, lamp pulses; `done` lamp and word `--teal-300`, no pulse; `refused` and `failed` lamp
and word `--red`.

### 2.4 The masthead (mobile)

The rail becomes a two-row masthead, full bleed, `--plate-navy`, `border-bottom: var(--bw-struct)
solid var(--teal-700)`:

```
grid-template-areas: "crest onair" "nav nav";
grid-template-columns: auto minmax(0, 1fr);
```

- Crest 96px wide, left, `--sp-4` padding.
- On-air block right aligned: lamp plus state word at `--t-state`. The Source line is dropped here;
  the Run view still shows it.
- Nav is a full-bleed row of three equal tabs, 50px tall, `--t-nav` Bungee, centred, active tab a
  solid `--teal-300` plate with `--accent-ink`. The Review count sits inline after the word.

### 2.5 The lower third

A `--plate-navy` plate, `--lt-h` tall, full width on mobile and under the work column only on
desktop. `hidden` unless a download event has
arrived, and hidden again on any terminal state.

```
grid-template-columns: minmax(0, 1fr) auto auto;
grid-template-areas: "cap   speed pct"
                     "title speed pct";
padding: var(--sp-3) var(--gutter);
border-top: var(--bw-struct) solid var(--teal-700);
```

- `.lt-meter` is the progress meter and it IS the plate's top edge: a 3px `--teal-300` bar absolutely
  positioned on the plate's top border, `transform: scaleX(p)`, `transform-origin: left`,
  `transition: transform 220ms linear`. Never animate `width`.
- `.lt-cap` `--t-label` `--ink-2`, the words "Now downloading".
- `.lt-title` `--t-title` `--ink`, one line, `text-overflow: ellipsis`.
- `.lt-speed` `--font-mono` `--t-data` `--ink-2`, right aligned; hidden when speed is null.
- `.lt-pct` Bungee `--t-pct` `--teal-300`; the `%` sign is a 0.45em `<i>` in Archivo 700, baseline
  aligned to the numeral's cap height.

Mobile: speed is dropped, the title truncates harder, `--t-pct` is 32px.

### 2.6 The context object

`app.js` hands each view one context object. Existing members keep their names and behaviour; the
new members are shell-owned and view-driven.

```js
{
  setBadge(count),                 // existing: the Review count in the rail nav
  setLamp(on),                     // existing: the on-air lamp
  setState(word, state),           // NEW: rail on-air word + `is-<state>` on .onair
  setSource(text),                 // NEW: the mono Source line under the state word ("" clears it)
  nowPlaying(data | null),         // NEW: the lower third. { title, speed, percent } or null to hide
}
```

Views must call `nowPlaying(null)` and `setSource("")` from their teardown. The rail never re-renders
on a route change.

---

## 3. Component vocabulary

Shared components live in `static/styles/shell.css`. A view file may only add view-specific rules. If
a shared component you need does not exist, add a view-local rule and report it as a finding rather
than editing another lane's file.

Every interactive component ships all seven states: default, hover, focus-visible, active, disabled,
loading (where it applies), error.

### 3.1 Buttons

One shape: a square block, `--ctl-h` tall, `padding-inline: var(--sp-5)`, `--t-btn` (Archivo 700
uppercase, 0.10em tracking), radius 0, no shadow. Labels are one word wherever possible and never
wrap. The fixed label vocabulary: Run, Accept, Manual, Hint, Skip, Cancel, Open review, Write these
Tags, Identify again.

| Class | Ground | Ink | Border | Hover | Active | Disabled |
|---|---|---|---|---|---|---|
| `.btn-primary` | `--teal-300` | `--accent-ink` | none | `--teal-500` ground | `translateY(1px)` | `--line` ground, `--ink-2` ink, `cursor: not-allowed` |
| `.btn-quiet` | transparent | `--ink` | `--bw-ctl` `--line` | border `--teal-500` | `translateY(1px)` | ink `--ink-2`, border `--line-soft` |
| `.btn-ghost` | transparent | `--ink-2` | none | ink `--ink`, underline offset 4px | `translateY(1px)` | ink `--line` |

Focus, on every interactive element without exception:
`outline: 3px solid var(--focus); outline-offset: 2px;` on `:focus-visible`. Never remove it, never
replace it with a shadow.

### 3.2 Inputs, selects, textarea

- Ground `--surface-2`, `--bw-ctl` solid `--line`, radius 0, `--ctl-h` tall,
  `padding-inline: var(--sp-4)`, `--t-title` weight 400, ink `--ink`.
- URL and path inputs use `--font-mono` at `--t-data`.
- Placeholder is `--ink-2` (12.24:1). Never a dimmed ink.
- `:hover` border `--teal-700`. `:focus-visible` border `--teal-300` plus the focus outline.
- `:disabled` ground `--bg`, border `--line-soft`, ink `--ink-2`.
- The label is always a separate element ABOVE the control, `--t-label`, `--ink-2`, `--sp-2` below
  it. No placeholder-as-label, anywhere.
- `select` keeps the native control, restyled only in ground, border and type. Do not build a custom
  dropdown.
- `input[type=number]` keeps its spinners.

### 3.3 Switch

Square track 46x24px, `--surface-2` ground, `--bw-ctl` `--line` border, radius 0. Knob is a 18px
square, `--line` when off, `--teal-300` when on, `transform: translateX(22px)`,
`transition: transform 160ms var(--ease-quart), background-color var(--d-press) linear`. The checkbox
itself stays in the DOM with its id, visually hidden but focusable; focus draws the ring on the
track. Track ground becomes `--teal-900` when checked.

### 3.4 Chip (Track state)

`--t-chip`, uppercase, 0.14em tracking, height 24px, `padding-inline: var(--sp-3)`, radius 0,
Archivo 700. Fixed set, and nothing else may be a chip:

| Chip | Ground | Ink |
|---|---|---|
| `VERIFIED` | `--teal-300` | `--accent-ink` |
| `REVIEW` | `--amber` | `--accent-ink` |
| `LIVE` | transparent, `--bw-ctl` `--teal-300` border | `--teal-300` |

### 3.5 Badge (the Review count)

Bungee, `--t-nav` size, `--amber`, no ground, no pill, no dot. `hidden` at zero. It is a number, not
a decoration.

### 3.6 Field label / legend

`--t-label`, Archivo 500, uppercase, 0.18em, `--ink-2`. Used for form labels, scoreboard legends
under a figure, the lower-third caption, and the tag-record's `dt`. Never used as an eyebrow above a
heading.

### 3.7 Set figure

The scoreboard unit. Bungee `--t-figure`, colour by role: verified `--teal-300`, queued `--amber`,
neutral counts `--ink`. A `--t-label` legend sits directly under it, `--sp-2` gap, both flush left
inside the figure block. Figures are grouped in a flex row with `--sp-6` gaps, flush right in the
view head.

### 3.8 Meter

Two forms, both `transform: scaleX()` on a filled bar, `transform-origin: left`, 220ms linear:

- **Lower-third meter**: the plate's own 3px top edge, `--teal-300` fill on a `--teal-900` track.
- **Inline meter** (`.meter`): 6px tall, `--teal-900` track, `--teal-300` fill, full width of its
  container. Used only where the lower third is not available.

Never animate `width`. Never use a spinner: loading is the state word plus the lamp.

### 3.9 Lamp

A 14px square (12px on mobile), no radius, no glow. Colour per state (2.3). While `running` it
pulses `opacity: 1 -> .35 -> 1` over 1.6s `ease-in-out` infinite. That is the only infinite animation
in the app, and it stops under reduced motion.

### 3.10 Plate and row

- **Plate**: a `--surface` block with `--sp-5` padding and no border, used where the ground genuinely
  changes (the tag record, the testimony panels on `--surface-2`, the inline decision panels, the
  appendix). Plates never nest inside plates. There are no cards in this design.
- **Row**: the default grouping. `padding-block: var(--sp-4)`, `border-bottom: var(--bw-hair) solid
  var(--line-soft)`, and nothing else. One bottom hairline per row, never top and bottom, and the
  last row in a list drops its border.

### 3.11 View head

Every view opens with the same three-part head, and no view may invent another:

```css
.view-head { display: grid; grid-template-columns: auto minmax(var(--sp-8), 1fr) auto;
             align-items: center; gap: var(--sp-5); }
.view-head .rule { height: var(--bw-struct); background: var(--rule); }
```

`h1` in Bungee at `--t-display`, uppercase, then the rule spanning the slack, then the scoreboard
flush right. Under it, `.view-sub` at `--t-lede` in `--ink-2`, max 62ch, `--sp-4` above and
`--sp-7` below. On mobile the head stacks: title, then the scoreboard as a row, then the sub. The
rule is `display: none` on mobile.

---

## 4. The crest

The mark is the brand and it is large. It appears once per screen in the rail, and once more at hero
scale in the Review empty state. It is never tinted, cropped, rotated, animated or used as an icon.

**One cut, printed white.** The rail is drenched in `--plate-navy` (`#0d1e3b`) and the shield's own
interior ink is `#071b36`, so `crest-teal.png` on that plate measures **1.86:1**: the badge reads as
a smudge and the crest teal the whole palette is sampled from is the one thing you cannot see. The
two-image keyline this section used to prescribe (the white silhouette printed behind the teal cut at
103.5%) did not rescue it either: at 240px the halo was about 2px and anti-aliased away, and at the
mobile size it did not exist at all.

The shipped mark is therefore the **white cut alone**, which sits at about 13:1 on the rail and keeps
every letterform and every crown point:

```html
<span class="crest">
  <img class="crest-mark" src="./assets/crest-white-480.png" alt="Clean Muzik"
       width="847" height="817">
</span>
```

```css
.crest      { display: block; width: 240px; max-width: 100%; }
.crest-mark { width: 100%; height: auto; }
```

There is no `.crest-key` element, no `crest-teal.png` in the rail, and no 103.5% knob. If the crest
teal is ever wanted inside the mark, the move is a lighter plate behind the crest only, giving the
badge its own ground instead of the rail's. It is never a keyline: that was tried, measured and
dropped.

| Placement | Width | File |
|---|---|---|
| Rail, desktop | 240px | `crest-outline-480.png` (the white render with its shaded crown, keyed from the checkerboard export) |
| Masthead, mobile | 96px | `crest-outline-480.png` |
| Review empty state, desktop | 300px | `crest-white-480.png` |
| Review empty state, mobile | 180px | `crest-white-480.png` |
| Favicon | 32px | `crest-teal-480.png` |

The teal cut survives at favicon size because there it sits on the browser's own chrome, never on
`--plate-navy`.

Both source PNGs are 847x817 (wider than tall; the brief's dimensions are transposed). Size the crest
by WIDTH and let height follow, and give every `<img>` `width="847" height="817"` so nothing reflows
on load.

`crest-teal.png` is 565KB and `crest-white.png` is 120KB, which would be the real first-paint cost of
this design. Foundation ships downscaled, palette-quantized copies at `assets/crest-teal-480.png`
(33KB) and `assets/crest-white-480.png` (18KB) and points the UI at those; the full-size originals
stay in the repo, referenced by nothing. See buildNotes for the exact command.

`logo.png` is retired from the UI. It stays on disk, referenced by nothing.

---

## 5. Views

Work-column width at 1440: 1440 - 360 rail - 96 gutters = **984px**. At 390: 390 - 40 = **350px**.

### 5.1 Run (`views/run.js` + `styles/run.css`)

**Head.** `RUN` / rule / three set figures: `VERIFIED` (teal), `QUEUED` (amber), `IN BATCH` (ink).
`IN BATCH` is `state.results.length`; do not invent a batch size the wire does not carry.

**Sub.** "One Source in, tagged Tracks out. Anything the Confidence gate cannot verify waits in
Review, and the batch never blocks." (The existing string with its em dash rewritten.)

**Form** (`.run-form`, keeps every id and the `<button type="submit">`):

```css
.url-row     { display: grid; grid-template-columns: minmax(0, 1fr) 168px; }
.options-row { display: flex; flex-wrap: wrap; align-items: end; gap: var(--sp-5); }
```

- `SOURCE` label above the URL input; the input and the Run button are butted with no gap, sharing
  a seam, both `--ctl-h`.
- Options row: the switch first (label to its right, sentence case "Playlist"), then three labelled
  fields at 132px: `LIMIT`, `FORMAT`, `CONCURRENCY`.
- `.inline-error` sits under the form: `--t-body`, `--red` ink, on `--bg`, with a
  `--bw-ctl` left-free full border in `--red`. No side-stripe borders.

**State line.** `<p class="run-state-line is-<state>">` stays, hidden when idle. It is the run's
DETAIL line, not a duplicate of the rail: for `running` and `done` it prints the Source URL in mono;
for `refused` and `failed` it prints the server's sentence in `--red`. The state WORD lives only in
the rail (`ctx.setState`).

**Tracklist.** `<ul class="tracklist">`, one row per result:

```css
.tracklist li { display: grid; grid-template-columns: 108px minmax(0, 1fr) auto;
                align-items: baseline; gap: var(--sp-4);
                min-height: var(--row-h); padding-block: var(--sp-4);
                border-bottom: var(--bw-hair) solid var(--line-soft); }
```

- Column 1: the chip.
- Column 2: `--t-title` Track title in `--ink`, artist appended in `--ink-2` at the same size and
  weight 400 (separated by a space, not a dash). A second line carries the reason in `--amber` at
  `--t-body` for review-bound rows, and the written `output_path` in mono `--t-data` `--ink-2` for
  verified rows (graft from the mixing-desk direction: `output_path` is on the wire and the current
  UI throws it away).
- Column 3: album and year, `--t-body` `--ink-2`, right aligned. On mobile this moves to the second
  line and the grid becomes `96px minmax(0,1fr)`.
- A `LIVE` row (the Track currently downloading) tints to `--surface` and takes the `LIVE` chip.
- **Do not render QUEUED placeholder rows.** The wire carries `results` plus the download event and
  nothing about the queue depth. Inventing rows is a contract fiction.

Above the list, a single `ARRIVED` legend in `--t-label` with a `--bw-hair` rule across the slack.
That is a legend for a list, not an eyebrow, and it is the only one in the view.

**Summary** (`.run-summary`, rendered at any terminal state): a `--surface` plate holding two set
figures at `--t-display` size (verified teal, queued amber) with their legends, plus an
`Open review` `.btn-quiet` when queued is non-zero.

**Appendix**: `Skipped`, `Already in the download manifest`, `Playlist file`, each a Bungee
`--t-head2` subhead over a two-column list at 1440 (`columns: 2; column-gap: var(--sp-8)`), one
column at 390. URLs and the playlist path are mono `--t-data`. It is quieter by position, never by
opacity.

**Mobile order** (graft from the poster direction). On a phone a run is watched far more often than
it is started. `run.js` sets `view.dataset.runState = state.state` on every render. Then:

```css
@media (max-width: 900px) {
  #view { display: flex; flex-direction: column; }
  [data-run-state="running"] .run-form { order: 2; }
  [data-run-state="running"] .stage    { order: 1; }
}
```

DOM order and tab order are unchanged, so the QA driver and the mock still fill the form the same
way. Only the visual order moves, and only while a run is live.

The download handler calls `ctx.nowPlaying({ title, speed, percent })`.

### 5.2 Review (`views/review.js` + `styles/review.css`)

**Head.** `REVIEW` / rule / `IN QUEUE` (amber) and `RULED TONIGHT` (ink). "Ruled tonight" is a
client-side counter incremented on each cleared decision and reset on view mount. No contract change.

**List.** `<ul class="review-list">`, each `<li class="review-item">` with the `.ri-head` button
(`aria-expanded`, toggling `.ri-body`) exactly as today:

```css
.ri-head { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto;
           align-items: center; gap: var(--sp-4); width: 100%;
           padding: var(--sp-4) 0; text-align: left;
           border-bottom: var(--bw-hair) solid var(--line-soft); }
```

Cover thumb 72px square (56px mobile) on `--teal-900` when absent; title `--t-title`; reason in
`--amber` at `--t-body`; the queue position as a Bungee figure at `--t-nav` size, right aligned.
An open item takes `background: var(--surface)`.

**Open body.**

```css
.ri-grid { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: var(--sp-6);
           padding: var(--sp-5) 0; }
```

Left: the cover at 300px square, then the native `<audio controls>` at full column width, . Do not skin the audio element.

Right: the tag record on a `--surface` plate, a four-column `dl`:

```css
.ri-tags dl { display: grid; grid-template-columns: auto minmax(0,1fr) auto minmax(0,1fr);
              gap: var(--sp-3) var(--sp-5); align-items: baseline; }
```

`dt` is `--t-label` `--ink-2`; `dd` is `--t-title` `--ink`. An absent value prints `not given` in
`--ink-2` (never a dash). Under it, the provisional note in `--t-body`: "Provisional Tags, best
effort, drawn from the Source. Nothing is written as verified until you rule."

**Testimony** (only when `item.conflict`), full width under the grid:

```css
.testimony        { border-top: var(--bw-struct) solid var(--rule); padding-top: var(--sp-5); }
.testimony .sides { display: grid; grid-template-columns: 1fr 1fr 1.6fr; gap: var(--bw-ctl); }
```

The 1:1:1.6 ratio is deliberate: three equal panels are a banned pattern. Panels sit on
`--surface-2` with `--sp-5` padding. Heading in Bungee `--t-head2`: "The Confidence gate could not
reconcile the testimony". Panel legends in `--t-label`: "What the fingerprint heard", "What the
Source claims", "What the gate ruled". The wide third panel carries the gate's sentence, then the
witness rationale as a `blockquote` at `--t-lede` on a `--surface` plate, then the attribution on
its own line in `--t-label`: "The identity witness". No dash before it.

**Decision bar.**

```css
.decision-bar { display: flex; align-items: center; gap: var(--sp-3);
                border-top: var(--bw-struct) solid var(--rule);
                padding-top: var(--sp-4); margin-top: var(--sp-5); }
```

A mono `--t-data` `--ink-2` note first (graft from the mixing-desk direction), printed only when
`item.output_path` exists: `Writes Tags to <output_path>`. Then `Accept` (`.btn-primary`), `Manual`
and `Hint` (`.btn-quiet`), a `.spacer` at `flex: 1`, and `Skip` (`.btn-ghost`) pushed right. Button
labels stay exactly these words: the QA driver looks them up by label.

Manual and Hint open `.decision-panel` inline, directly under the bar, on `--surface-2`: labels
above inputs, a two-column tag form, submit plus Cancel. **Never a modal.**

**The four rulings** (graft from the poster direction). A persistent block at the foot of the view,
shown in both the populated and the empty state, because it teaches the interface without a tour:

```css
.rulings { display: grid; grid-template-columns: 96px minmax(0, 1fr);
           gap: var(--sp-3) var(--sp-5); max-width: 62ch; }
```

Bungee `--t-head2` heading "The four rulings", then four rows: term in `--teal-300` `--t-label`,
definition in `--t-body` `--ink`.

- Accept: write the provisional Tags as verified.
- Manual: type the Tags yourself, then write them.
- Hint: nudge another Identification pass.
- Skip: leave the file untagged and move on.

**Empty state** (`.all-clear`, the class stays):

```css
.all-clear { display: grid; grid-template-columns: 300px minmax(0, 1fr);
             gap: var(--sp-8); align-items: center; padding-block: var(--sp-9); }
```

`crest-white-480.png` at 300px left; Bungee `--t-empty` "Nothing awaits your ear" right, then "Every
Track passed the Confidence gate or has been ruled on. The queue is clear, sir." at `--t-lede`, then
a `Back to Run` `.btn-quiet`. Stacks to one column at 390 with the crest at 180px.

**Mobile.** `.ri-grid` becomes one column in the order cover, audio, tag record (two-column `dl`),
so the thing you listen to comes before the thing you read. `.sides` stacks with the gate panel last.
The decision bar wraps: Accept full width, Manual and Hint side by side, Skip full width below. Every
target is at least `--tap`.

### 5.3 Settings (`views/settings.js` + `styles/settings.css`)

**Head.** `SETTINGS` / rule / the current format as a set figure (`M4A` or `MP3 320`) with the legend
`CURRENT FORMAT`. `savedNote` keeps `role="status"` and prints "Saved." beside the format heading.

**Format choice.** Two full-width plates stacked, 96px tall each, `--sp-3` apart. Not a card row,
not a grid.

```css
.format-choice label { display: grid; grid-template-columns: 26px minmax(0, 1fr) auto;
                       align-items: center; gap: var(--sp-4);
                       background: var(--surface); padding: var(--sp-5);
                       border: var(--bw-ctl) solid transparent; }
.format-choice label.selected { border-color: var(--teal-300); background: var(--surface-2); }
```

A 26px square selection indicator (filled `--teal-300` when selected, `--bw-ctl` `--line` keyline
when not), the name in Archivo 700 `--t-plate`, the description in `--t-body` `--ink-2` under it,
and a right-aligned state word in `--t-label`: `SAVED` in `--teal-300` when selected, `SELECT` in
`--ink-2` otherwise. The radio inputs stay in the DOM, visually hidden, focusable; focus draws the
ring on the plate.

**How this works.** Bungee `--t-head2` heading, then the existing prose as a two-column block at
1440 (`columns: 2; column-gap: var(--sp-9); max-width: 116ch`), one column at 390. Glossary terms
(Source, Track, Match, Confidence gate, Tags, Resolver, Authority, Review queue) are `--teal-300`
Archivo 600 inline, not bold ink. Paragraphs are separated by space, not rules. **Not a five-cell
grid, not cards**: it is prose in two columns.

---

## 6. The equaliser (removed)

The mock's equaliser horizon (a full-width canvas band under the shell, driven by run state, download
percent and Review audio) shipped in #85 and was removed on 2026-09-16 as visual clutter. `eq.js`,
`eq.css`, the `.horizon` wrapper, the `ctx.eq` handle and the `--horizon-h`, `--z-eq`, `--d-settle`
and `--red-900` tokens went with it. The work column now runs to the bottom of the viewport, and the
lower third sits directly in the shell grid.

---

## 7. Motion vocabulary

Only `transform` and `opacity` are animated. Never `width`, `height`, `top` or `left`.

| Moment | What moves | Duration / easing |
|---|---|---|
| Track arrives | `opacity 0->1`, `translateY(6px)->0` | `--d-arrive` `--ease-quart`, staggered 40ms, capped at 6 items |
| Download progress | `scaleX` on the lower-third meter | 220ms linear (an eased meter lies about the rate) |
| Run lamp while running | `opacity 1 -> .35 -> 1` | 1.6s ease-in-out infinite |
| State change | on-air word and lamp crossfade | `--d-state` |
| Review row open | `grid-template-rows: 0fr -> 1fr`, chevron rotates 90deg | `--d-open` `--ease-quart` |
| Ruled row clearing | `opacity -> 0`, `translateX(12px)`, row collapse | `--d-clear` (matches `decide()`) |
| Buttons | background shift; `translateY(1px)` on `:active` | `--d-press` |
| View change | work column crossfade only | `--d-state`. The rail does not re-render |

Row and Track arrival animations **enhance an already-visible default**. Never gate content
visibility behind a class-triggered transition: a headless render or a hidden tab would ship a blank
list.

Reduced motion, one global block in `tokens.css`:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important; animation-iteration-count: 1 !important;
    transition-duration: .01ms !important; scroll-behavior: auto !important;
  }
}
```

plus the lamp stops pulsing.

---

## 8. Copy rules

- Sentence case everywhere except display type, chips, buttons and labels, which are uppercase by
  CSS `text-transform`, not by typing capitals into the string.
- **Zero em dashes and zero en dashes.** Rewrite every one currently in the views. The known list:
  - `run.js` view sub: "...cannot verify waits in Review, and the batch never blocks."
  - `run.js` track row artist join: a space, not `" — "`.
  - `run.js` appendix skip reason: drop the leading dash, put the reason in its own span.
  - `review.js` `dd()` empty value: `"not given"`, not `"—"`.
  - `review.js` provisional note: "Provisional Tags, best effort, drawn from the Source. Nothing is
    written as verified until you rule."
  - `review.js` attribution: "The identity witness", no leading dash.
  - `review.js` `decide()` messages: "Still unverified. It stays in the queue." and
    "Still unverified. <reason>"; the 409 line: "<message> Refreshing the queue."
  - `settings.js` format descriptions: "AAC as YouTube serves it. No re-encode, the cleanest copy
    available." and "Re-encoded to MP3 at 320 kbps, for players that insist on it."
  - `settings.js` "How this works" prose: every dash rewritten as a full stop, comma or colon.
  - The `mp3 · 320` label loses its middle dot: `mp3 320`.
- `dev-mock.js` is out of scope for the sweep. The brief freezes that file beyond fixtures, so only
  fixture copy the UI renders as content (the mock Track's `reason`) was rewritten; the mock's own
  simulated 409 sentences keep their dashes and were reverted after being edited in round 2. They
  are visible only under `?mock=1`, and only when a decision is posted against a stale queue.
- No exclamation marks. No "Oops". No filler verbs.
- Glossary words only, spelled as `CONTEXT.md` spells them: Source, Track, Tags, Match, Confidence
  gate, Review queue, Authority, Resolver, identity witness, Identity verdict, Download manifest,
  Playlist file.
- Numbers are real. Never invent a count the wire does not carry.
- Errors are plain and inline, next to the thing that failed. Never `alert()`, never a toast.
- The empty state teaches the next action; it never just says "nothing here".

---

## 9. Do not

1. Do not add a light theme, a theme toggle, or any section that inverts. Dark only, by decision.
2. Do not use `#000` or pure white. `--bg` and `--ink` are the extremes.
3. Do not use Bungee on a button label, chip, field label, data value, table cell or paragraph.
   See 1.2 for the seven places it is allowed.
4. Do not set any functional text below full opacity. `--ink-2` is a colour, not `opacity: .7`.
5. Do not centre the layout, add `max-width` with `margin: 0 auto`, or wrap a view in a container.
   The work column runs to the right edge.
6. Do not put an eyebrow above a heading. Uppercase tracked type is a field label, a legend or a
   chip, and nothing else.
7. Do not build a card. Rows with one bottom hairline, plates where the ground genuinely changes.
   Plates never nest.
8. Do not build a three-equal-column row anywhere. The testimony is 1:1:1.6; the settings prose is
   two columns; the format choice is two stacked full-width plates.
9. Do not use a modal, a toast, a spinner, a custom scrollbar, a custom cursor, a hand-rolled SVG
   icon, or a skinned `<audio>` player.
10. Do not add a neon glow, a blur, a glass panel, a gradient on text, or a drop shadow.
11. Do not add a decorative status dot. The lamp and the chips carry real state; nothing else gets a
    dot.
12. Do not animate `width`, `height`, `top` or `left`. Progress is `scaleX`.
13. Do not set `overflow` on a container inside a view. `.work` is the only scroll container.
14. Do not add an equaliser, visualiser or other ambient decoration loop. It was tried and removed.
15. Do not change `api.js` request shapes, `wire.py`, the routes, the view module signatures, or
    `dev-mock.js` beyond adding fixtures.
16. Do not render placeholder rows, counts or paths the wire does not supply.
17. Do not use `innerHTML` with any server- or user-provided string. `el()` from `dom.js`, always.
18. Do not link to `fonts.googleapis.com`. Fonts are self-hosted woff2 and the page must render with
    no network.
19. Do not add a hamburger. Three nav items fit on one line at 390.
20. Do not introduce a border radius.

---

## 10. Lane map

| Files | Owner | Sections of this document |
|---|---|---|
| `index.html`, `app.js`, `dom.js`, `styles/tokens.css`, `styles/shell.css`, `assets/**` | Foundation | 1, 2, 3, 4, 7 |
| `views/run.js`, `styles/run.css` | Run | 5.1 |
| `views/review.js`, `styles/review.css` | Review | 5.2 |
| `views/settings.js`, `styles/settings.css` | Settings | 5.3 |

`styles.css` is deleted by Foundation. `index.html` links the split files as separate `<link>`
elements, in this order: `tokens.css`, `shell.css`, `run.css`, `review.css`,
`settings.css`. No `@import`.
