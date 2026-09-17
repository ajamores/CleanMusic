"""Re-check harness — re-runs a Review queue through today's identification and gate.

The safety net #91 asked for. After a change to identification or the Confidence
gate, the question is always the same: which entries of the last real batch's
Review queue would the code *now* verify, and which correctly stay put? This
answers it without touching anything on disk.

For each queue entry whose audio is still on disk it re-reads the Source's
metadata (title, uploader, description — yt-dlp, no download), then drives the
engine's own per-Track pipeline (``_process_track``) against the real Shazam,
AcoustID and Haiku witness. Only the writes are stubbed: the tag writer records
nothing, and the album tiers (MusicBrainz, the Resolver's album guess) are skipped
— they don't bear on the verdict and would only add cost. Nothing is re-implemented,
so the row reports exactly what today's gate decided.

Shazam isn't fully repeatable run to run (2 of 32 changed answer on the #91 corpus),
so compare *outcomes* across runs, not raw fingerprint strings.

Run:  python tools/recheck.py downloads/review-queue.jsonl > retest/recheck.jsonl
Output: one JSONL row per Track on stdout; progress and a tally on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from muzik.domain import IdentityRuling, Match, ReviewItem, Tags, Track
from muzik.engine import Providers, _process_track
from muzik.providers import Fingerprinter, Resolver


@dataclass
class _Seen:
    """What the recording seams captured while one Track ran."""

    shazam: Match | None = None
    acoustid: Match | None = None
    ruling: IdentityRuling | None = None
    witnessed: list[Match | None] = field(default_factory=list)


class _Recording:
    """Wraps a Fingerprinter: remembers its answer, returns it unchanged."""

    def __init__(self, inner: Fingerprinter, seen: _Seen, slot: str) -> None:
        self._inner, self._seen, self._slot = inner, seen, slot

    def identify(self, track: Track) -> Match | None:
        match = self._inner.identify(track)
        setattr(self._seen, self._slot, match)
        return match


class _WitnessOnly:
    """Wraps a Resolver: records the identity ruling; never guesses an album."""

    def __init__(self, inner: Resolver, seen: _Seen) -> None:
        self._inner, self._seen = inner, seen

    def resolve(self, track: Track, match: Match | None) -> Match | None:
        return None

    def witness_identity(
        self, track: Track, match: Match, second: Match | None = None
    ) -> IdentityRuling:
        self._seen.witnessed.append(second)
        ruling = self._inner.witness_identity(track, match, second)
        self._seen.ruling = ruling
        return ruling


class _NoAlbumAuthority:
    """Tags straight from the Match; no MusicBrainz album lookups."""

    def tags_for(self, match: Match) -> Tags:
        return Tags(title=match.title, artist=match.artist, album=match.album, verified=False)

    def canonical_album(self, isrc: str | None) -> str | None:
        return None

    def canonical_album_for_recording(self, recording_mbid: str | None) -> str | None:
        return None


class _NoWrite:
    """A tag writer that writes nothing — the re-check is read-only."""

    def write(self, track: Track, tags: Tags) -> Path:
        return track.audio_path


class _NoDownload:
    def download(self, source):  # pragma: no cover - the pipeline never downloads here
        raise AssertionError("re-check never downloads")


def _identity(match: Match | None) -> dict | None:
    if match is None:
        return None
    return {"title": match.title, "artist": match.artist, "tied": len(match.tied)}


def _path(seen: _Seen, reason: str | None) -> str:
    """Which path the Track took: fast (corroborated), witness (uncorroborated),
    contradicted, or — with Shazam silent — an AcoustID rescue or a miss. AcoustID is
    null on the fast and contradicted paths: the gate never consults it there (#38)."""
    if seen.ruling is not None:
        return "witness"
    if seen.shazam is None:
        return "rescue" if seen.acoustid is not None else "miss"
    return "fast" if reason is None else "contradicted"


def recheck_item(
    item: ReviewItem,
    track: Track,
    shazam: Fingerprinter,
    acoustid: Fingerprinter,
    resolver: Resolver,
) -> dict:
    """Re-run one queued Track through today's pipeline; one report row."""
    seen = _Seen()
    providers = Providers(
        downloader=_NoDownload(),
        fingerprinter=_Recording(shazam, seen, "shazam"),
        authority=_NoAlbumAuthority(),
        resolver=_WitnessOnly(resolver, seen),
        tagwriter=_NoWrite(),
        acoustid=_Recording(acoustid, seen, "acoustid"),
    )
    result = _process_track(track, providers)
    return {
        "source_url": item.source_url,
        "source_title": track.source_title,
        "uploader": track.uploader,
        "old_reason": item.reason,
        "shazam": _identity(seen.shazam),
        "acoustid": _identity(seen.acoustid),
        # The second opinion the witness actually saw — after the #87 tie-break.
        "witnessed_second": _identity(seen.witnessed[0]) if seen.witnessed else None,
        "path": _path(seen, result.reason),
        "outcome": "verified" if result.reason is None else "review",
        "reason": result.reason,
        "verdict": seen.ruling.verdict if seen.ruling is not None else None,
        "rationale": seen.ruling.rationale if seen.ruling is not None else None,
    }


def _track_from_source(item: ReviewItem, audio_path: Path) -> Track:
    """The Track as the batch saw it: metadata re-read from YouTube, audio from disk."""
    import yt_dlp

    from muzik.real.downloader import _track_from_entry

    opts = {"quiet": True, "no_warnings": True, "remote_components": ["ejs:github"]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(item.source_url, download=False, process=False)
    track = _track_from_entry(info, audio_path.parent, audio_path.suffix, item.source_url)
    return replace(track, audio_path=audio_path)


def main() -> int:
    from dotenv import load_dotenv

    from muzik.real.fingerprinter import RateLimitedFingerprinter, ShazamFingerprinter
    from muzik.real.review_queue import JsonReviewQueue
    from muzik.wiring import _SHAZAM_MIN_INTERVAL, build_acoustid, build_resolver

    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="recheck", description="Re-run a Review queue through today's gate (read-only)."
    )
    parser.add_argument("queue", type=Path, help="A review-queue.jsonl to re-check")
    args = parser.parse_args()

    shazam = RateLimitedFingerprinter(ShazamFingerprinter(), min_interval=_SHAZAM_MIN_INTERVAL)
    acoustid = build_acoustid()
    resolver = build_resolver()

    tally: dict[str, int] = {}
    for item in JsonReviewQueue(args.queue).items():
        audio_path = item.audio_path or item.output_path
        if audio_path is None or not audio_path.exists():
            print(f"skip (no audio on disk): {item.source_url}", file=sys.stderr)
            continue
        try:
            track = _track_from_source(item, audio_path)
            row = recheck_item(item, track, shazam, acoustid, resolver)
        except Exception as error:  # one dead video must not end the re-check
            print(f"skip ({error.__class__.__name__}: {error}): {item.source_url}", file=sys.stderr)
            continue
        print(json.dumps(row, ensure_ascii=False), flush=True)
        key = f"{row['path']} → {row['outcome']}"
        tally[key] = tally.get(key, 0) + 1
        print(f"{key:<24} {row['source_title']}", file=sys.stderr)

    print("\nTally:", file=sys.stderr)
    for key, count in sorted(tally.items()):
        print(f"  {key:<24} {count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
