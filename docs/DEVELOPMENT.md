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

## Running the CLI

```bash
.venv/bin/muzik "https://www.youtube.com/watch?v=<id>" --out downloads
```

Add `--cookies <file>` for age-restricted Sources.
