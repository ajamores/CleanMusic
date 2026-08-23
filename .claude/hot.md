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

- `main` HEAD `c84827a`, clean. Core pipeline complete and live-verified: download → fingerprint → album waterfall (Shazam → MusicBrainz-by-ISRC → Resolver) → Confidence gate → tag or Review queue. #4/#7/#8/#22/#24/#25 all merged.
- **This session's landings:** #37 shipped (`PR #39`) — the Track now captures the Source's **description, tags, and thumbnail URL** (`domain.py` + `downloader._track_from_entry`), the gating prerequisite for #38. Pure capture, inert: nothing consumes the fields yet. Earlier: #32 fix (`PR #34`), `tools/observe.py` (`PR #35`), ADR-0006 accepted (`PR #36`).
- **deno installed** and on PATH (`~/.bashrc`) — the smoke suite (`pytest -m smoke`) now runs instead of skipping; offline suite 132 green.

## The big decision this session (ADR-0006, Accepted)

**Identity today rests on Shazam alone**, spot-checked only against the Source title/channel; MusicBrainz + Resolver touch only the *album*. An observation run (`tools/observe.py`, 14-track playlist) proved **real Shazam confidence is binary** — every match is hard-coded `1.0` (`fingerprinter.py`), so the `0.9` uploader-only bar (#16) can never fire. Also: the download discards description/tags/thumbnail (only title/channel/duration survive), so the "AI reasons over all evidence" vision in `CONTEXT.md` is unbuilt.

**Decided (option 3):** the Resolver becomes an **identity witness** — reasons over fingerprint + full download + thumbnail, rules consistent/inconsistent/can't-tell, and the gate verifies on that verdict. Recorded in `docs/adr/0006-identity-evidence-combination.md` (the spec) and `docs/LEARNINGS.md` (the binary-confidence lesson).

## What's next — pick up here

- **#38** — *Resolver becomes an identity witness; gate verifies on its verdict.* The epic that closes #16 + #17. `ready-for-agent`, **now unblocked** (#37 landed). **Start here:** `/implement 38`.
  - **Speed is a hard requirement** (Armand, this session): the identity-witness AI call must NOT slow the common case. Fire the Resolver verdict **only on the uncorroborated path** — a title-corroborated Track still verifies with no AI call. **Measure wall-clock before/after** (baseline via `tools/observe.py` on a known playlist) and report the delta; bound the call with a timeout that degrades to `can't tell`→Review (ADR-0002). Requirement is pinned as a comment on #38 and in memory (`pipeline-speed-sensitive`).
- #16 / #17 kept open for reference, off the frontier (commented, `ready-for-agent` removed); #38 closes them when built.

## Recent sessions (rolling — last 2–3)

- **2026-08-23 (#37)** — Implemented + merged #37 (`PR #39`): Track captures the Source's description/tags/thumbnail URL. Thumbnail carried as URL, not bytes (pure capture, no new network I/O; #38 fetches bytes on demand). Two-axis review clean. Unblocks #38; Armand flagged pipeline speed as a hard requirement for #38's AI call.
- **2026-08-23** — Implemented #32 (archive-skip abort fix, `PR #34`). Then a design thread: built `tools/observe.py`, ran it on a real 14-track playlist, found Shazam confidence is binary → #16's threshold premise is dead. Drafted + accepted ADR-0006 (Resolver as identity witness). Cut tickets #37 (prereq) + #38 (epic); re-pointed #16/#17. Installed deno.
- **2026-08-21 (#22)** — Single-Track-by-default + `--playlist` opt-in + bare-playlist refusal (`PlaylistInSingleModeError`, yt-dlp pre-flight). Merged; unblocked #25.
- **2026-08-21** — Live sanity-check + triage; filed #24 (silent archived re-run) and #25 (`.m3u8` grouping). Both since built/merged.

## Where the rest of the context lives

- **Decisions:** `docs/adr/` — `0001`–`0006` (`0006` = the identity-evidence decision). **Glossary:** `CONTEXT.md`. **Spec:** issue #1.
- **Tickets:** **#38** (next, unblocked — speed-sensitive, see comment); reference **#16**/**#17** (closed by #38). #37 done (`PR #39`).
- **Observation harness:** `tools/observe.py` (`python tools/observe.py <url>`); output → gitignored `retest/observe/`.
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work) — incl. the binary-Shazam-confidence lesson. **Dev setup:** `docs/DEVELOPMENT.md` (needs deno on PATH for smoke tests).
- **Prototype code + verdict tables:** branch `prototype/identify-spike`. **Garden vault:** `/graft` to push, not this board.
