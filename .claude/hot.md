---
type: meta
title: "Hot — muziktest"
updated: 2026-08-23
tags: [meta, hot-cache]
status: evergreen
---

# Hot — muziktest (Muzik: YouTube download + auto-tag)

> This is the repo's own working-memory board. Cache, not journal — overwritten each save.

## What this repo is

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script); core engine + CLI now, web later. Real providers wired in `cli.py`: yt-dlp, **Shazam** fingerprint, **MusicBrainz** album-by-ISRC, **Haiku** Resolver, MP3/M4A writers, JSON review queue. Identity comes from the fingerprint; the Resolver is the **identity witness** the gate verifies on (ADR-0006).

## Current State (2026-08-23)

- **On `main`, clean.** #42 merged (`PR #44`, squash → `6e8fada`); #42 closed. Nothing in flight.
- **#42 shipped + live-verified.** Confidence gate now consults the identity witness on **every** title-agreeing-but-not-title-corroborated Match (not just the no-artist-witness case) — catches reversed "Song - Artist" titles, "Dj" prefixes, artist-across-the-dash. `consistent` → verified with the fingerprint's Tags, never the reversed Source parse; title *disagreements* stay off the AI path (speed, #38). Dropped two now-dead `_conflict_why` branches; synced `observe.py`'s `consults_witness` diagnostic to the new predicate.
- **Live proof (`tools/observe.py` on `PLBLcoq9Bb-FU`):** track 11 ("Buscando La Verdad - Ricky Campanelli", fingerprint "Dj Ricky Campanelli") now **verifies** with the fingerprint's Tags. Speed: +1 witness call on the 14-track run, ~1.9 s on a 101 s run. Offline suite 147 green (3 smoke deselected).
- **Ticket frontier is empty** of `ready-for-agent` work: only #1 (master spec) remains open. The #16/#17/#38 epic is fully shipped.

## Where to next

- The queue is dry. Next work must be **generated**, not picked up — an on-ramp, not `/implement`:
  - `/triage` if bug reports / requests have piled up (things not self-authored),
  - `/improve-codebase-architecture` for upkeep,
  - `/grill-with-docs` for a new Muzik idea (web UI, batch-review UX).
- Decide that door in a **fresh session**.

## Recent sessions (rolling — last 2–3)

- **2026-08-23 (#42)** — Broadened the gate's witness path (sibling of #41). Built test-first, two-axis review clean (fixed a CONTEXT.md "song" glossary drift; flagged + honoured the #38 speed rule). Live-verified track 11 on `PLBLcoq9Bb-FU` — re-hit the archived-`--out` trap (`docs/LEARNINGS.md`) on the first run, re-ran into a fresh dir. PR #44.
- **2026-08-23 (#41 / #38)** — #38 shipped (`PR #40`): Resolver became the identity witness, gate verifies on its verdict (closed #16/#17). #41 shipped (`PR #43`): grammatical stopwords ignored in title agreement.
- **2026-08-23 (#37)** — #37 (`PR #39`): Track captures the Source's description/tags/thumbnail URL — the prerequisite that unblocked #38.

## Where the rest of the context lives

- **Decisions:** `docs/adr/` — `0001`–`0006` (`0006` = Resolver as identity witness). **Glossary:** `CONTEXT.md`. **Spec:** issue #1.
- **Observation harness:** `tools/observe.py` (`python tools/observe.py <url>`); output → gitignored `retest/` (use a **fresh `--out`** dir — a reused one's archive skips everything).
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work). **Dev setup:** `docs/DEVELOPMENT.md` (needs deno on PATH for smoke tests).
- **Prototype:** branch `prototype/identify-spike`. **Garden:** `/graft`, not this board.
