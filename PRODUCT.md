# Clean Muzik

## What it is

A personal tool that downloads audio from a YouTube Source and writes clean, verified Tags into
each Track. One Source in, tagged Tracks out. Anything the Confidence gate cannot verify waits in
the Review queue with provisional Tags, and the batch never blocks.

The web UI is a thin adapter over the same engine the CLI drives (ADR-0010). It has three views:
Run (submit a Source, watch the batch live over SSE), Review (clear the queue in one pass: listen,
weigh the testimony, rule), and Settings (one knob, the download format, plus a plain account of
how the pipeline thinks).

## Who uses it

One person: Armand Amores, who owns the brand the crest belongs to. Nobody else has an account,
because there are no accounts. He runs it in the evening beside a music library, on a laptop, and
checks a running batch from a phone over Tailscale, sometimes from a car. There is no onboarding,
no marketing surface, no first-run tour. He already knows what everything means.

## Register

**Product UI.** Design serves the product, not the other way round. The tool is in a task: submit a
Source, watch it work, clear a queue. Familiarity is a feature; strangeness without purpose is the
failure mode. Density is allowed and often correct.

The one place the register bends: the brand is assertive on purpose. The crest is large and always
on screen, and the equaliser carries state as flavour. That is a deliberate, bounded exception, and
it never reaches into form controls, data values or labels.

## Theme

**Dark only, by decision.** There is no light theme, no theme toggle, and no section that inverts.
The tool is used at night beside a stereo. Do not add `prefers-color-scheme` handling.

## Domain vocabulary

UI copy uses the project's own glossary, and only that: Source, Track, Tags, Match, Confidence gate,
Review queue, Authority, Resolver, identity witness, Identity verdict, Download manifest, Playlist
file, Artist normalisation. Definitions and the words to avoid are in `CONTEXT.md` at the repo root.
Read it before writing any string.

## Voice

Dry, understated, plain. Sentence case. No exclamation marks. No em dashes or en dashes anywhere.
"Nothing awaits your ear" is the register: calm, a little formal, never cute.

## Constraints that shape the design

- Vanilla ES modules, no build step, no framework, no npm dependency, served by FastAPI StaticFiles.
- API CONTRACT v1 is frozen (`src/muzik/web/wire.py`, `static/api.js`).
- Every server- or user-provided string goes through `textContent`, never `innerHTML`.
- The page must render with no network: fonts are self-hosted woff2 in `static/assets/fonts/`.
- 390px is a first-class layout, not a fallback.
- The tool is fast and must feel instant. The equaliser must not cost it.

## Design system

`DESIGN.md` at the repo root is the authoritative visual spec. Read it before touching any file
under `src/muzik/web/static/`.
