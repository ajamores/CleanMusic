---
type: meta
title: "Hot — muziktest"
updated: 2026-08-21
tags: [meta, hot-cache]
status: evergreen
---

# Hot — muziktest (Muzik: YouTube download + auto-tag)

> This is the repo's own working-memory board. Cache, not journal — overwritten each save.

## What this repo is

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** (title/artist/album/art) into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script). Core engine + CLI now, web later. Real providers are built and wired in `cli.py`: yt-dlp download, **Shazam** fingerprint (`shazamio`), **MusicBrainz** album-by-ISRC, **Haiku** Resolver, MP3/M4A tag writers, JSON review queue. Identity comes from the audio fingerprint; the fakes are test doubles for whole-box tests. Wave 2 is polish, not the core build.

## Current State (2026-08-21)

- Branch **`feat/22-single-song-default-playlist`** (commit `ba6805f`) — **#22 built, 86 tests green, PR open to close #22**. `main` HEAD `5cf94dc`; #4/#7/#8 merged. Core engine complete: download → fingerprint → album waterfall (Shazam → MusicBrainz-by-ISRC → Resolver) → Confidence gate → tag or Review queue.
- **#22 done** — *single Track by default; `--playlist` to expand.* Downloader gained `expand_playlist` → `noplaylist = not expand_playlist` in `_build_opts`; single mode runs a yt-dlp pre-flight (`extract_info(process=False)`, `_type == 'playlist'`) and refuses a bare playlist via `PlaylistInSingleModeError` (whole-Source rejection, not a per-Track skip) before any download. CLI `--playlist` per-run, never persisted; refusal exits `2`. Two-axis review clean (fixed "song"→"Track" help, aligned message to ADR-0004). Implements ADR-0004.
- **Confirmed working end-to-end live** (prior session) — `youtu.be/akaI9JgeO9c` → Marvin Gaye — *Trouble Man*, real album Tags + embedded cover art. File saved as `downloads/<video-id>.m4a` (id filename by design; library re-groups by Tags).

## What's next

- **Merge the #22 PR**, then close #22. After merge, `main` carries `--playlist`.
- **#25 is now unblocked** — *write an `.m3u8` playlist file when `--playlist` expands a list* (preserve the user's monthly "Aug 2026" grouping). `ready-for-agent`; its blocker (#22) is built and PR'd. Grouping lives in the `.m3u8` beside the files; album Tags stay the real album.
- **#24 needs triage** — *surface download progress + explain the already-archived no-op.* `needs-triage`: a re-run where every Track is already in `.download-archive.txt` silently prints `0 verified, 0 queued` (hit this live). Verbosity contract is a product call for Armand before it's buildable.
- Before any worktree fan-out: **`git push` the prep commit first** (worktrees branch from pushed remote — `docs/LEARNINGS.md`).

## Parked (filed, blocked on live provider behaviour)

- **#16** — confident-wrong Match on an impersonator channel still verifies.
- **#17** — Resolver-proposed albums get `verified` without an independent check (gate cross-checks the Source title, not the Resolver). Sibling of #16.

## Recent sessions (rolling — last 2–3)

- **2026-08-21 (#22)** — Built single-Track-by-default + `--playlist` opt-in + bare-playlist refusal (`PlaylistInSingleModeError`, yt-dlp pre-flight). 9 new offline tests (86 green). Two-axis review clean. Branch `feat/22-single-song-default-playlist`, PR open. Unblocks #25.
- **2026-08-21** — Live sanity-check + triage. Diagnosed the silent `0 verified, 0 queued` re-run (archived video-id) → filed **#24**. Confirmed Tags/cover write cleanly (Marvin Gaye — *Trouble Man*). Settled video-id-vs-title filename (id wins). Filed **#25** (`.m3u8` grouping, blocked-by #22).
- **2026-08-20 (#8)** — Playlist + bounded concurrency: `ThreadPoolExecutor` in `run()`, `RateLimitedAuthority` (~1 req/s), JSONL O(1) crash-safe queue, yt-dlp `download_archive`. 17 new tests. Two-axis review clean. Merged.
- **2026-08-20 (#7)** — Review-queue clear pass (accept/manual/hint/skip) over a `ReviewPrompter` seam. Merged PR #19.

## Where the rest of the context lives

- **Decisions:** `docs/adr/` — `0001`/`0002`/`0003`/`0004`. **Glossary:** `CONTEXT.md`. **Spec:** issue #1.
- **Tickets:** **#22** built (PR open); **#25** now unblocked; **#24** needs-triage; parked **#16**, **#17**.
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work). **Dev setup:** `docs/DEVELOPMENT.md`.
- **Prototype code + verdict tables:** branch `prototype/identify-spike`.
- **Garden vault** (business/decisions): `/graft` to push, not this board.
