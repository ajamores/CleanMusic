---
type: meta
title: "Hot — muziktest"
updated: 2026-08-20
tags: [meta, hot-cache]
status: evergreen
---

# Hot — muziktest (Muzik: YouTube download + auto-tag)

> This is the repo's own working-memory board. Cache, not journal — overwritten each save.

## What this repo is

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** (title/artist/album/art) into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script). Core engine + CLI now, web later. Real providers are built and wired in `cli.py`: yt-dlp download, **Shazam** fingerprint (`shazamio`), **MusicBrainz** album-by-ISRC, **Haiku** resolver, MP3/M4A tag writers, JSON review queue. Identity comes from the audio fingerprint; the fakes are test doubles for whole-box tests. Wave 2 is polish, not the core build.

## Current State (2026-08-20)

- Branch **`main`**, in sync with `origin/main` (HEAD `95c3aeb`). **38 tests green.**
- **#14 shipped and closed** (PR #15): the Confidence gate no longer stamps a low-confidence, **channel-only** Match `verified`. When the artist agreement rests solely on the uploader (a channel name anyone can set), the Match must clear `_UPLOADER_ONLY_MIN_CONFIDENCE = 0.9` or it's kept unverified → Review queue. A title-corroborated artist is unaffected. Recorded as an ADR-0003 amendment.
- Pipeline shape: `download → _album_waterfall → _confidence_gate → _write`; `run()` also enqueues reviewables + drains `downloader.skipped`.

## What's next

- **Wave 2 continues, one ticket per fresh session.** Ready: **#8** (Playlist + bounded concurrency), **#4** (Resolver / Claude Haiku). **#7** (clear the queue) needs only **#4**.
- Loop per ticket: `/clear` → `/implement` (drives `/tdd` then `/code-review`) → commit → PR → merge → close. Small already-diagnosed fixes: `/tdd` alone.
- Before any worktree fan-out: **`git push` the prep commit first** (worktrees branch from pushed remote — `docs/LEARNINGS.md`).

## Open threads

- **Residual gate gap (known, accepted for now):** #14 only closes the *low-confidence* channel-impersonation case. A **confident-wrong** Match on a channel named after the wrong artist still verifies — no test separates a real artist channel from one merely named after the artist. Revisit once the real Fingerprinter lands (its confidence distribution is what sets the bar).
- **Queue write is O(n²)/batch** — noted in `review_queue.py` docstring; revisit for #8's playlists (JSON Lines appends O(1)).

## Recent sessions (rolling — last 2–3)

- **2026-08-20 (#14)** — Gated the uploader-only verify path on `Match.confidence`. Filed the weakness (surfaced in the #6 review) as an issue first, TDD'd the fix, two-axis review (dedup cleanup + added the missing high-confidence test), ADR-0003 amendment. Merged PR #15.
- **2026-08-20 (#6)** — Persisted Review queue + summary; all `DownloadError`s route to the queue. Merged PR #13.
- **2026-08-20 (#11)** — Artist-aware Confidence gate; uploader as second witness. ADR-0003.

## Where the rest of the context lives

- **Decisions:** `docs/adr/` — `0001`/`0002`/`0003` (0003 now carries the #14 amendment). **Glossary:** `CONTEXT.md`. **Spec:** issue #1. **Tickets:** #4, #7, #8.
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work). **Dev setup:** `docs/DEVELOPMENT.md`.
- **Prototype code + verdict tables:** branch `prototype/identify-spike`.
- **Garden vault** (business/decisions): `/graft` to push, not this board.
