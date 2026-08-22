# Development

## Requirements

- **Python 3.10 or 3.11.** Not 3.14 — `shazamio-core` ships no wheel for it and its
  Rust build fails from source. `yt-dlp` prints a deprecation warning on 3.10 but works;
  3.11 avoids the warning.
- **ffmpeg** on `PATH` — used to extract audio and to down-convert clips for fingerprinting.
- **A JavaScript runtime** on `PATH` — [deno](https://deno.land) (`curl -fsSL https://deno.land/install.sh | sh`) is yt-dlp's recommended one. yt-dlp now needs it for YouTube extraction; without it it falls back to a deprecated path that pulls degraded audio, which weakens the fingerprint and sends tracks to review that should verify (`docs/LEARNINGS.md`).
- **`uv`** for environment and dependency management.

## Setup

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
```

An `ANTHROPIC_API_KEY` in `.env` is needed only for the Resolver (Claude Haiku); the
skeleton's happy path and the whole test suite run without it.

## Running the tests

```bash
.venv/bin/pytest
```

All tests run offline. The two real-I/O tests (`test_tagwriter.py`,
`test_engine_integration.py`) need `ffmpeg` and skip if it is absent.

### Smoke test (real yt-dlp)

An **opt-in** integration test drives the real pipeline against real yt-dlp on the
critical paths #24 touched — a fresh download, an archived re-run, and `--playlist`
expansion — because the offline suite fakes the yt-dlp seam and a fake can't
disprove a wrong assumption about the tool (this is how #28/#29 shipped). It is a
pre-merge check, not a CI gate.

```bash
.venv/bin/pytest -m smoke
```

It is **deselected by default** (`pytest` alone never runs it) and needs the network
plus a full download toolchain — `yt-dlp`, `ffmpeg`, and **deno** (the JS runtime;
see Requirements above). Missing any of those, each case **skips** rather than
fails. The fixture video/playlist ids are pinned at the top of
`tests/test_smoke_yt_dlp.py`; if one is taken down, repoint that one constant.

## Running the CLI

```bash
.venv/bin/muzik "https://www.youtube.com/watch?v=<id>" --out downloads
```

Add `--cookies <file>` for age-restricted Sources.
