# CleanMusic

CleanMusic identifies the recordings in a YouTube video or playlist, downloads the audio, and writes verified music tags and cover art into each file. The Python package and command are called `muzik`.

It is a personal tool. Most of the design effort went into deciding when a tag is trustworthy enough to write, and into testing that decision.

## How identification works

Each Track is identified by how it sounds. Shazam fingerprints the audio, and when `fpcalc` is installed, AcoustID fingerprints it again as a second identity witness. The video title is only used to check the result.

Every Match then goes through the Confidence gate, which compares it with the Source's own title. A Match that fails the gate is never written as verified. The Track gets provisional tags instead and waits in a Review queue.

When the title offers no independent sign of the artist, an AI Resolver (Claude Haiku) acts as an identity witness. It reads the title, channel, description and thumbnail, and rules whether the Match is consistent with them.

Album and cover art come from Shazam first, then MusicBrainz. The Resolver is asked only if the album is still unresolved after both.

A failure or timeout at any step sends that one Track to Review, and the rest of the batch keeps going.

Design decisions are recorded in [`docs/adr/`](docs/adr/). [`CONTEXT.md`](CONTEXT.md) defines the domain vocabulary, such as Source, Track, Match and Confidence gate.

## Testing

| Layer | What it does | How to run |
|---|---|---|
| Offline suite | 300 pytest cases. Every external service (yt-dlp, Shazam, AcoustID, MusicBrainz, the Resolver) is replaced by a fake at a clean seam. The tag-writing tests use real files: 1-second clips generated with ffmpeg. CI runs the suite on every push and pull request. | `pytest` |
| Live contract tests | Opt-in tests against the real services. A test skips when a key, the network or a tool is missing, so an absent dependency never shows up as a failure. | `pytest -m smoke` |
| Benchmarking harness | [`tools/observe.py`](tools/observe.py) runs a real batch and records, for each Track, what the pipeline computes but doesn't print: the fingerprint result, the gate path it took, the source that placed the album, and the identity witness's verdict and how long it took. | `python tools/observe.py "<url>"` |

A fake behaves the way its author believes the real service behaves, so it can't catch a wrong belief. Live runs have caught defects that the offline suite passed:

- Real Shazam confidence is always `1.0`, so a 0.9 threshold could never fail on real data.
- yt-dlp filters already-archived entries during extraction, as well as at download, which broke re-run detection.

Both are written up in [`docs/LEARNINGS.md`](docs/LEARNINGS.md).

## How it is built

Development runs as an agentic workflow in Claude Code. A written spec (issue #1) is split into scoped GitHub issues. Each issue is built on its own branch and merged through a pull request along with its tests, and architecture decisions are recorded as ADRs.

## Requirements

- Python 3.10 or 3.11. Python 3.14 won't work, because `shazamio-core` has no wheel for it.
- `ffmpeg` on `PATH`
- [`uv`](https://github.com/astral-sh/uv)
- Optional: `fpcalc` (Chromaprint) for AcoustID, and [deno](https://deno.land) for reliable YouTube extraction

[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) has the full details, including API keys.

## Setup and usage

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"

.venv/bin/pytest              # offline suite
.venv/bin/pytest -m smoke     # live contract tests (network and keys)
.venv/bin/muzik --help
```

API keys go in `.env`. `ANTHROPIC_API_KEY` enables the Resolver, and the optional `ACOUSTID_API_KEY` enables the AcoustID witness. The offline suite needs neither.

## A note on downloads

CleanMusic is built for personal use. It downloads audio you have the right to access, for your own library, and it doesn't host or redistribute anything.
