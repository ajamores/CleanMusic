# Muzik

Identifies the recordings in a YouTube video or playlist and writes clean, verified music tags and cover art into the downloaded audio files.

It is a personal tool. The interesting part is how it decides a tag is trustworthy enough to write, and how that decision is tested.

## How identification works

- **Acoustic fingerprinting.** Each Track is identified by what it sounds like (Shazam), not by parsing the video title. AcoustID acts as a second identity witness when `fpcalc` is installed.
- **Confidence gate.** Every Match is cross-checked against the Source's own title. A Match that fails the gate is never written as verified: the Track gets provisional tags and goes to a Review queue.
- **Identity witness.** When the title offers no independent artist signal, an AI Resolver (Claude Haiku) rules whether the Match is consistent with the full evidence: title, channel, description and thumbnail.
- **Tag waterfall.** Album and cover art come from Shazam first, then MusicBrainz, then the Resolver only if still unresolved.
- **Batches never block.** A failure or timeout in any tier degrades that one Track to Review; it never aborts the batch.

Design decisions are recorded in [`docs/adr/`](docs/adr/). The domain vocabulary (Source, Track, Match, Confidence gate) is defined in [`CONTEXT.md`](CONTEXT.md).

## Testing approach

| Layer | What it does | How to run |
|---|---|---|
| **Offline suite** | 300 pytest cases. Every external service (yt-dlp, Shazam, AcoustID, MusicBrainz, the Resolver) is replaced with a fake at a clean seam; real-file tag-writing tests generate 1-second clips with ffmpeg. Runs in CI on every push and pull request. | `pytest` |
| **Live contract tests** | Opt-in tests against the real services. Each one skips, never fails, when a key, the network or a tool is unavailable. | `pytest -m smoke` |
| **Benchmarking harness** | [`tools/observe.py`](tools/observe.py) drives a real batch and records, per Track, what the pipeline computed but never emits: the fingerprint result, which gate path it took, which waterfall tier placed the album, and the identity witness verdict and its cost. | `python tools/observe.py "<url>"` |

**Why live runs exist.** A fake encodes the same assumption as the code it stands in for, so it cannot disprove that assumption. Live runs caught defects the offline suite passed:

- Real Shazam confidence is always `1.0`, which made a 0.9 threshold unable to fail on real data.
- yt-dlp filters archived entries during extraction, which broke re-run detection.

Each is written up in [`docs/LEARNINGS.md`](docs/LEARNINGS.md).

## How it is built

Agentic workflow in Claude Code:

1. A written spec (issue #1) is broken into scoped GitHub issues.
2. Each issue is built on its own branch and merged through a pull request with its tests.
3. Architecture decisions are recorded as ADRs.

## Requirements

- Python 3.10 or 3.11 (not 3.14; `shazamio-core` has no wheel for it)
- `ffmpeg` on `PATH`
- [`uv`](https://github.com/astral-sh/uv)
- Optional: `fpcalc` (Chromaprint) for AcoustID, and [deno](https://deno.land) for reliable YouTube extraction

Full details, including API keys, are in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Setup and usage

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"

.venv/bin/pytest              # offline suite
.venv/bin/pytest -m smoke     # live contract tests (network and keys)
.venv/bin/muzik --help
```

API keys go in `.env`:

- `ANTHROPIC_API_KEY` enables the Resolver.
- `ACOUSTID_API_KEY` enables the AcoustID witness and is optional.

The offline suite needs neither key.

## A note on downloads

Built for personal use: it downloads audio you have the right to access for your own library. It does not host or redistribute content.
