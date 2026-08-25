---
type: meta
title: "Hot — muziktest"
updated: 2026-08-25
tags: [meta, hot-cache]
status: evergreen
---

# Hot — muziktest (Muzik: YouTube download + auto-tag)

> This is the repo's own working-memory board. Cache, not journal — overwritten each save.

## What this repo is

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script); core engine + CLI now, web later. Provider seams wired in `cli.py`: yt-dlp, **Shazam** fingerprint, **AcoustID** second fingerprint, **MusicBrainz** album-by-ISRC/recording, **Haiku** Resolver, MP3/M4A writers, thumbnail fetcher, JSON review queue. Identity comes from the fingerprint; the Resolver is the **identity witness** the gate verifies on (ADR-0006).

## Current State (2026-08-25)

- **On `main`, clean.** Three tickets shipped this session's chain: #45, #52, #51.
- **#51 done (PR #55, `2423c3f`).** AcoustID is a **second acoustic witness** fed to the ADR-0006 witness — not a blind fallback. Runs only on the uncorroborated + Shazam-miss paths; the corroborated fast path stays Shazam-only (test-enforced). Album hydrates by MusicBrainz recording id (reuses #45's tier), primary Match only. New dep `pyacoustid`; needs `fpcalc` + `ACOUSTID_API_KEY` (self-disables without them).

## Frontier (open — priority order)

- **#46 — live contract smoke tests (`ready-for-agent`).** Shazam / MusicBrainz / Haiku. MB (#45) and yt-dlp (#30) smokes exist, and #51 added an AcoustID smoke — but Shazam and Haiku live contracts are still unwritten. The gap that hid #45.
- **#47 — artist-name normalisation across written Tags (spec US#26, `ready-for-agent`, unbuilt).**
- **#48 — route classical Tracks to Review (spec US#25, `ready-for-human`).** Needs a human decision first.
- **#49 — harden idempotency / archive re-run detection (`ready-for-human`).** Needs a human decision first.
- **#50 — 60s fingerprint window (`needs-triage`, low).**

## Recent sessions (rolling — last 2–3)

- **2026-08-25 — #51 AcoustID second witness.** Merged via PR #55. Branched off main *after* merging #52 first (kept #51 an independent PR). Two-axis review caught a throwaway MB lookup on the second-opinion path → fixed by the recording-id design.
- **2026-08-25 — #52 artwork fallback.** Thumbnail as fallback cover art so no Track ships bare (PR #54). Added shared `real/images.fetch_thumbnail`.
- **Earlier — #45 MusicBrainz album tier fix (PR #53).** Two-lookup ISRC→recording→release-groups; unblocked #51.

## Where the rest of the context lives

- **Decisions:** `docs/adr/` (`0006` = identity witness, now amended for #51). **Glossary:** `CONTEXT.md`. **Spec:** issue #1 (closed).
- **Observation harness:** `tools/observe.py` (`python tools/observe.py <url>`); output → gitignored `retest/` (fresh `--out`). **Smoke:** `pytest -m smoke` (opt-in; skips w/o network/toolchain).
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work). **Dev setup:** `docs/DEVELOPMENT.md` (needs deno + ffmpeg + `fpcalc` on PATH). **Garden:** `/graft`, not this board.
