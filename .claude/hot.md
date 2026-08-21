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

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** (title/artist/album/art) into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script). Core engine + CLI now, web later. Real providers are built and wired in `cli.py`: yt-dlp download, **Shazam** fingerprint (`shazamio`), **MusicBrainz** album-by-ISRC, **Haiku** Resolver, MP3/M4A tag writers, JSON review queue. Identity comes from the audio fingerprint; the fakes are test doubles for whole-box tests. Wave 2 is polish, not the core build.

## Current State (2026-08-20)

- Branch **`main`** (HEAD `00eeb59`, #7 merged). **#8 built locally, 76 tests green, uncommitted** — next step is commit → PR → merge → close.
- **#8 done** (Playlist + bounded concurrency): `engine.run()` fans `_process_track` across a bounded `ThreadPoolExecutor` (`_DEFAULT_CONCURRENCY=4`, `run(..., concurrency=)`), results in Track order, enqueue on the main thread (single-writer queue). **`RateLimitedAuthority`** wraps the Authority — throttles only `canonical_album` to ~1 req/s (ADR-0002), `tags_for` passes through; wired in `cli.py`. **`JsonReviewQueue` → JSON Lines**: O(1) append, torn-tail-tolerant read (`_has_unterminated_tail` closes a torn tail before append; `_load` skips unparseable lines). yt-dlp **`download_archive`** in out_dir skips already-fetched Tracks on re-run; `FakeDownloader` gained an archive sim + `--concurrency` CLI flag. Queue file renamed `review-queue.json` → `.jsonl`.
- **#7 done** (PR #19): Review-queue clear pass — accept / manual / hint / skip over a `ReviewPrompter` seam.
- Waterfall complete: fingerprint album → MusicBrainz-by-ISRC → Resolver.

## What's next

- Commit #8, open PR, merge, close #8. Two-axis review already run — clean (no hard findings; addressed the test-dedup + AC3 end-to-end coverage notes).
- Wave 2 remaining tickets, one per fresh session. Loop: `/clear` → `/implement` → commit → PR → merge → close.
- Before any worktree fan-out: **`git push` the prep commit first** (worktrees branch from pushed remote — `docs/LEARNINGS.md`).

## Parked (filed, blocked on live provider behaviour)

- **#16** — confident-wrong Match on an impersonator channel still verifies.
- **#17** — Resolver-proposed albums get `verified` without an independent check (gate cross-checks the Source title, not the Resolver). Sibling of #16.

## Recent sessions (rolling — last 2–3)

- **2026-08-20 (#8)** — Playlist + bounded concurrency: `ThreadPoolExecutor` in `run()`, `RateLimitedAuthority` (~1 req/s), JSONL O(1) crash-safe queue, yt-dlp `download_archive`. 17 new tests (76 green). Two-axis review clean.
- **2026-08-20 (#7)** — Review-queue clear pass (accept/manual/hint/skip) over a `ReviewPrompter` seam. Merged PR #19.
- **2026-08-20 (#4)** — Wired the Resolver as the album waterfall's final tier + graceful key handling. Filed #17 from the spec-axis note. Merged PR #18.

## Where the rest of the context lives

- **Decisions:** `docs/adr/` — `0001`/`0002`/`0003`. **Glossary:** `CONTEXT.md`. **Spec:** issue #1. **Tickets:** #7, #8; parked #16, #17.
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work). **Dev setup:** `docs/DEVELOPMENT.md`.
- **Prototype code + verdict tables:** branch `prototype/identify-spike`.
- **Garden vault** (business/decisions): `/graft` to push, not this board.
