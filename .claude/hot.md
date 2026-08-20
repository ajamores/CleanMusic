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

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** (title/artist/album/art) into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script). Core engine + CLI now, web later. Building phase.

## Current State (2026-08-20)

- Branch **`main`**, pushed & clean (HEAD `f11f513`, `origin/main` in sync). Untracked: `uv.lock` (deliberately, so far).
- **#3, #5, #9 shipped and closed** — built in parallel via worktree agents, integrated onto the pipeline seams, two-axis reviewed. **21 tests green.**
- Engine pipeline is now `download → _album_waterfall (#3) → _confidence_gate (#5) → _write`; #9's format/cookies rode in via constructor injection (no engine/domain change).
- Review fixes folded into #9: age-marker `"age"`→`"webpage"` substring bug; dead `yt_dlp_codec` wired in.

## What's next

- **Wave 2, one ticket per fresh session.** Ready now: **#8** (Playlist + bounded concurrency), **#4** (Resolver / Claude Haiku — unblocked by #3), **#11** (Confidence gate: carry `uploader` on Track, artist-aware check + fallback — refines #5), **#6→#7** (Review queue — follows #5).
- **Before any worktree fan-out: `git push` the prep commit first** — worktrees branch from the pushed remote, not local HEAD (see `docs/LEARNINGS.md`). Today's stumble.
- Loop per ticket: `tdd` → two-axis `code-review` → commit → close.
- Deferred review notes now owned by tickets: skipped-Source Review-queue routing → #6/#7; real Downloader aborts a whole playlist on one bad entry → #8.

## Recent sessions (rolling — last 2–3)

- **2026-08-20 (pm)** — Merged #2 (PR #10). Fanned out #3/#5/#9 as parallel worktree agents; hit the pushed-remote base gotcha (banked as a learning), recovered by grafting each stage onto the widened pipeline seam. Two-axis review caught + fixed the age-substring bug and a dead property; filed #11 from the gate design discussion.
- **2026-08-20 (am)** — Built #2 skeleton TDD; two-axis review fixes; closed #2.

## Where the rest of the context lives

- **Decisions:** `docs/adr/0001` (engine/interface split), `docs/adr/0002` (identification pipeline). **Glossary:** `CONTEXT.md`. **Spec:** issue #1. **Tickets:** #4, #6, #7, #8, #11.
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work). **Dev setup:** `docs/DEVELOPMENT.md`.
- **Prototype code + verdict tables:** branch `prototype/identify-spike`.
- **Garden vault** (business/decisions): `/graft` to push, not this board.
