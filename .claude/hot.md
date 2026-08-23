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

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** (title/artist/album/art) into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script). Core engine + CLI now, web later. Real providers built and wired in `cli.py`: yt-dlp download, **Shazam** fingerprint (`shazamio`), **MusicBrainz** album-by-ISRC, **Haiku** Resolver, MP3/M4A tag writers, JSON review queue. Identity comes from the audio fingerprint; fakes are test doubles for whole-box tests.

## Current State (2026-08-23)

- `main` HEAD `01afbcc`, clean. Core pipeline complete and live-verified: download → fingerprint → album waterfall (Shazam → MusicBrainz-by-ISRC → Resolver) → Confidence gate → tag or Review queue. #4/#7/#8/#22/#24/#25 all merged.
- **This session's landings:** #32 fixed (archive-skip path no longer aborts a batch on a mid-resolve `DownloadError` or a non-`FileNotFoundError` archive read — `PR #34`). Observation harness `tools/observe.py` added (`PR #35`). ADR-0006 accepted (`PR #36`).
- **deno installed** and on PATH (`~/.bashrc`) — the smoke suite (`pytest -m smoke`) now runs instead of skipping; 3 smoke + 127 offline green.

## The big decision this session (ADR-0006, Accepted)

**Identity today rests on Shazam alone**, spot-checked only against the Source title/channel; MusicBrainz + Resolver touch only the *album*. An observation run (`tools/observe.py`, 14-track playlist) proved **real Shazam confidence is binary** — every match is hard-coded `1.0` (`fingerprinter.py`), so the `0.9` uploader-only bar (#16) can never fire. Also: the download discards description/tags/thumbnail (only title/channel/duration survive), so the "AI reasons over all evidence" vision in `CONTEXT.md` is unbuilt.

**Decided (option 3):** the Resolver becomes an **identity witness** — reasons over fingerprint + full download + thumbnail, rules consistent/inconsistent/can't-tell, and the gate verifies on that verdict. Recorded in `docs/adr/0006-identity-evidence-combination.md` (the spec) and `docs/LEARNINGS.md` (the binary-confidence lesson).

## What's next — pick up here

- **#37** — *Capture description, tags, thumbnail onto the Track.* The prerequisite (today only title/channel/duration are captured). `ready-for-agent`, unblocked. **Start here:** `/implement 37`.
- **#38** — *Resolver becomes an identity witness; gate verifies on its verdict.* The epic that closes #16 + #17. `ready-for-agent`, **blocked-by #37** (native GitHub dependency). Do after #37, `/clear` context between.
- #16 / #17 kept open for reference, off the frontier (commented, `ready-for-agent` removed); #38 closes them when built.

## Recent sessions (rolling — last 2–3)

- **2026-08-23** — Implemented #32 (archive-skip abort fix, `PR #34`). Then a design thread: built `tools/observe.py`, ran it on a real 14-track playlist, found Shazam confidence is binary → #16's threshold premise is dead. Drafted + accepted ADR-0006 (Resolver as identity witness). Cut tickets #37 (prereq) + #38 (epic); re-pointed #16/#17. Installed deno.
- **2026-08-21 (#22)** — Single-Track-by-default + `--playlist` opt-in + bare-playlist refusal (`PlaylistInSingleModeError`, yt-dlp pre-flight). Merged; unblocked #25.
- **2026-08-21** — Live sanity-check + triage; filed #24 (silent archived re-run) and #25 (`.m3u8` grouping). Both since built/merged.

## Where the rest of the context lives

- **Decisions:** `docs/adr/` — `0001`–`0006` (`0006` = the identity-evidence decision). **Glossary:** `CONTEXT.md`. **Spec:** issue #1.
- **Tickets:** **#37** (next, unblocked), **#38** (blocked-by #37); reference **#16**/**#17**.
- **Observation harness:** `tools/observe.py` (`python tools/observe.py <url>`); output → gitignored `retest/observe/`.
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work) — incl. the binary-Shazam-confidence lesson. **Dev setup:** `docs/DEVELOPMENT.md` (needs deno on PATH for smoke tests).
- **Prototype code + verdict tables:** branch `prototype/identify-spike`. **Garden vault:** `/graft` to push, not this board.
