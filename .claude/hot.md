---
type: meta
title: "Hot — muziktest"
updated: 2026-08-30
tags: [meta, hot-cache]
status: evergreen
---

# Hot — muziktest (Muzik: YouTube download + auto-tag)

> This is the repo's own working-memory board. Cache, not journal — overwritten each save.

## What this repo is

Muzik — downloads music from a YouTube **Source** and writes verified **Tags** into each **Track**. Python (`uv`, `src/muzik`, `muzik` console script); core engine + CLI + **Clean Muzik web UI** (`python -m muzik.web`, ADR-0010). Provider seams wired in `wiring.py` (shared by both adapters): yt-dlp, **Shazam** fingerprint (rate-limited 1s + retry, #63), **AcoustID** second fingerprint, **MusicBrainz** album lookup, **Haiku** identity witness (ADR-0006), MP3/M4A writers, JSON review queue.

## Current State (2026-08-30)

- **Web UI landed on branch `web-ui`** (two commits: the feature + this board), awaiting PR to `main`. Strays left uncommitted on purpose: `docs/research/`, `tailscale-explainer.html` (other sessions').
- **Clean Muzik web UI built end-to-end** (8-agent workflow): FastAPI sibling adapter over the engine (ADR-0010, `src/muzik/web/`), SPA with live SSE batch progress + Review queue (conflict testimony, audio preview, cover art) + settings, `--demo` mode on `fakes.py`, crest logo branding. Engine gained `run(on_result=…)` + downloader `on_event` streaming seams. 330 offline tests green. Run: `uv sync --extra web && uv run python -m muzik.web --demo`.
- **The Bury-Me-A-G triptych (#82 #83 #84), all `needs-triage`:** one Track exposed all three waterfall tiers in one evening — Shazam invented Gabrielle (#82: contradicted path never consults AcoustID, which had the right answer + MBID; refined: identity witness seated on the concordant-fingerprints case only); hint clear left the rejected Match's cover art embedded (#83: accept-vs-hint None-semantics conflict); Resolver's last-resort album guess named the wrong volume, "Thug Motivation 101" vs *The Inspiration* (#84: MB text search before Resolver on the hint path). Track itself fully corrected by hand (tags + CAA art). Flowchart artifact: "The Second Witness".
- **Epic #66 (seed the library, 404-Track playlist): all gates closed, mid-verification.** Shipped today: #62 per-Track guard, #63 Shazam throttle, #69 `--limit N`, #71 dead-entry guard, #73 witness album-cover fix, #74 witness rationale in output (PRs #67/68/70/72/76/77).
- **Slice run (20) done:** 17 verified, 1 review (cleared). Dup entry at positions 12/13; dead entries at 353/357/404 → now clean skips.
- **Navidrome — actual setup (corrected 2026-08-29, NOT docker):** native Linux binary `/usr/local/bin/navidrome`, systemd unit `navidrome.service` (enabled, auto-starts), config `/etc/navidrome/navidrome.toml`, bound `0.0.0.0:4533`. **MusicFolder = `/mnt/c/Users/aj_am/Music`** (Armand's real library, 255 files) — NOT the repo's `downloads/` (the 404 Muzik test tracks are a separate pile Navidrome does not serve; that's intentional per Armand). First visit http://localhost:4533 creates the admin user; `.m3u8` imports only after that. (Earlier board's `navidrome-muzik` docker container claim was wrong.)
- **Remote access WORKING (2026-08-29) — car goal via Tailscale.** Tailscale 1.102.3 installed in WSL (`tailscaled` systemd service, auto-starts), authed as armand.amores1@, WSL tailnet IP **`100.69.71.72`** — Navidrome verified reachable there (HTTP 200). Phone side: Tailscale app (same account, toggle on) + a Subsonic client (Symfonium/Tempo/substreamer) pointed at `http://100.69.71.72:4533` → aux cord → car. **Caveat: WSL/Navidrome only live while the Windows host is awake** (sleep kills the server). Offline file-sync to phone (Syncthing) is the wanted-but-not-priority follow-up that removes that dependency.

## Next (epic #66 remainder)

1. `time uv run muzik "<playlist-url>" --playlist --limit 100` — note wall-clock (throttle Fog, #63).
2. Then `--limit 150`, then full (no limit).
3. Verify in Navidrome: `.m3u8` import, artist grouping, artwork.
4. `muzik --review` to clear; the queue's real size decides UI scope → ticket it, close #66.

Watch for: repeat witness false-inconsistents (rationale now prints — `witness: "…"` line); the two >10-min tracks (evidence for #50); AcoustID missing newer/indie tracks is normal.

## Frontier (open, none gating the runs)

- #82 second-witness re-identify, #83 hint-path stale art, #84 hint-path album via MB search — the triptych; #82's spec is near `ready-for-agent` after the case-2 refinement.
- #65 manifest-tick-after-tagging — deferred unless a run bites (#64 shipped).
- #75 show AcoustID's opinion in output — post-epic polish.
- #50 60s fingerprint window (watch), #48 classical routing (`ready-for-human`).

## Recent sessions (rolling — last 2–3)

- **2026-08-30 — web UI + the Bury-Me-A-G triptych.** 8-agent workflow built the Clean Muzik web UI end-to-end (seams → build → integrate → polish → adversarial review, 5 findings fixed); first run died on session limit, resumed clean from cache. Live re-fetch of one deleted Track then exposed #82/#83/#84 (above); Track corrected manually via MusicBrainz + Cover Art Archive. "The Second Witness" flowchart artifact published.
- **2026-08-29 — car access: Navidrome reachable from the road.** Stood up Tailscale in WSL (IP `100.69.71.72`), verified Navidrome answers on it; phone plays via a Subsonic app over aux cord. Corrected the stale docker claim — Navidrome is a native WSL systemd binary serving `/mnt/c/Users/aj_am/Music`. No repo code changed (pure infra).
- **2026-08-26 — epic #66 gates + slice + witness bug.** Six tickets shipped (above). Slice run exposed a reproducible witness false-negative: Haiku anchored on the album cover's printed title over all text evidence → fixed deterministically by withholding the cover on auto-generated uploads (#73, live-verified 6/6); LEARNINGS entry filed. Smoke suite green (needs `.env` keys exported manually).

## Where the rest of the context lives

- **Decisions:** `docs/adr/`. **Glossary:** `CONTEXT.md`. **Tickets/epic:** GitHub Issues (#66 map, evidence in its comments).
- **Paid-for mistakes:** `docs/LEARNINGS.md` (read before work). **Dev setup:** `docs/DEVELOPMENT.md` (deno + ffmpeg + `fpcalc`). **Smoke:** `pytest -m smoke`. **Garden:** `/graft`, not this board.
