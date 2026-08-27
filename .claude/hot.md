---
type: meta
title: "Hot — muziktest"
updated: 2026-08-26
tags: [meta, hot-cache]
status: evergreen
---

# Hot — muziktest (Muzik: YouTube download + auto-tag)

> This is the repo's own working-memory board. Cache, not journal — overwritten each save.

## What this repo is

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script); core engine + CLI now, web later. Provider seams wired in `cli.py`: yt-dlp, **Shazam** fingerprint (rate-limited 1s + retry, #63), **AcoustID** second fingerprint, **MusicBrainz** album lookup, **Haiku** identity witness (ADR-0006), MP3/M4A writers, JSON review queue.

## Current State (2026-08-26)

- **On `main`, clean** except a pre-existing unexplained `uv.lock` modification (not this session's).
- **Epic #66 (seed the library, 404-Track playlist): all gates closed, mid-verification.** Shipped today: #62 per-Track guard, #63 Shazam throttle, #69 `--limit N`, #71 dead-entry guard, #73 witness album-cover fix, #74 witness rationale in output (PRs #67/68/70/72/76/77).
- **Slice run (20) done:** 17 verified, 1 review (cleared). Dup entry at positions 12/13; dead entries at 353/357/404 → now clean skips.
- **Navidrome up for verification:** docker container `navidrome-muzik`, port 4533, music = `downloads/` (ro), data `~/navidrome/data`, 1-min rescan. **First visit http://localhost:4533 must create the admin user — the `.m3u8` imports only after that.** (An older stopped `navidrome` container belongs to `~/github/music-stack` — untouched.)

## Next (epic #66 remainder)

1. `time uv run muzik "<playlist-url>" --playlist --limit 100` — note wall-clock (throttle Fog, #63).
2. Then `--limit 150`, then full (no limit).
3. Verify in Navidrome: `.m3u8` import, artist grouping, artwork.
4. `muzik --review` to clear; the queue's real size decides UI scope → ticket it, close #66.

Watch for: repeat witness false-inconsistents (rationale now prints — `witness: "…"` line); the two >10-min tracks (evidence for #50); AcoustID missing newer/indie tracks is normal.

## Frontier (open, none gating the runs)

- #64 incremental queue/`.m3u8` writes, #65 manifest-tick-after-tagging — deferred unless a run bites.
- #75 show AcoustID's opinion in output — post-epic polish.
- #50 60s fingerprint window (watch), #48 classical routing (`ready-for-human`).

## Recent sessions (rolling — last 2–3)

- **2026-08-26 — epic #66 gates + slice + witness bug.** Six tickets shipped (above). Slice run exposed a reproducible witness false-negative: Haiku anchored on the album cover's printed title over all text evidence → fixed deterministically by withholding the cover on auto-generated uploads (#73, live-verified 6/6); LEARNINGS entry filed. Smoke suite green (needs `.env` keys exported manually).
- **2026-08-25 — #51 AcoustID second witness** (PR #55), plus #52 artwork fallback, #45 MusicBrainz album tier.

## Where the rest of the context lives

- **Decisions:** `docs/adr/`. **Glossary:** `CONTEXT.md`. **Tickets/epic:** GitHub Issues (#66 map, evidence in its comments).
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work). **Dev setup:** `docs/DEVELOPMENT.md` (deno + ffmpeg + `fpcalc`). **Smoke:** `pytest -m smoke`. **Garden:** `/graft`, not this board.
