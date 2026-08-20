"""The core engine: the single entry point over the five provider seams.

Interface-agnostic (ADR-0001) — it knows nothing about the CLI or a future web
adapter. It takes a Source and returns one TrackResult per downloaded Track.

Flow (ticket #2): download → fingerprint → album waterfall → confidence gate →
write. Each stage is its own function so later tickets extend one seam without
touching the others: #3/#4 grow ``_album_waterfall``, #5 fills ``_confidence_gate``,
#9 grows ``_write``. The skeleton's stages are pass-throughs (ADR-0002).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from muzik.domain import Match, Source, Tags, Track, TrackResult
from muzik.providers import (
    Authority,
    Downloader,
    Fingerprinter,
    Resolver,
    TagWriter,
)


@dataclass(frozen=True)
class Providers:
    """The five injected providers the engine runs against."""

    downloader: Downloader
    fingerprinter: Fingerprinter
    authority: Authority
    resolver: Resolver
    tagwriter: TagWriter


def run(source: Source, providers: Providers) -> list[TrackResult]:
    """Process a Source end to end, returning one result per Track.

    The per-Track pipeline lives in ``_process_track``; this loop is the seam
    #8 replaces with bounded concurrency.
    """
    results: list[TrackResult] = []
    for track in providers.downloader.download(source):
        results.append(_process_track(track, providers))
    return results


def _process_track(track: Track, providers: Providers) -> TrackResult:
    """The pipeline for a single Track: identify → album → gate → write."""
    match = providers.fingerprinter.identify(track)
    if match is None:
        return _review(track, "no fingerprint match")
    tags = _album_waterfall(match, providers)
    tags = _confidence_gate(track, match, tags)
    output_path = _write(track, tags, providers)
    return TrackResult(
        source_url=track.source_url,
        tags=tags,
        output_path=output_path,
        status="tagged",
    )


def _album_waterfall(match: Match, providers: Providers) -> Tags:
    """Canonical Tags for a Match (ADR-0002).

    Skeleton: pass the Fingerprinter's own Match through the Authority. #3 adds
    the MusicBrainz-by-ISRC tier, #4 the Resolver tier.
    """
    return providers.authority.tags_for(match)


def _confidence_gate(track: Track, match: Match, tags: Tags) -> Tags:
    """Cross-check the Match against the Source title before writing (ADR-0002).

    Skeleton: pass-through. #5 marks Tags verified on agreement, or replaces
    them with provisional Tags on a mismatch.
    """
    return tags


def _write(track: Track, tags: Tags, providers: Providers) -> Path:
    """Write Tags into the Track's file, returning its path.

    Skeleton: default format. #9 adds output-format selection (M4A/MP3 320).
    """
    return providers.tagwriter.write(track, tags)


def _review(track: Track, reason: str) -> TrackResult:
    """A Track that could not be tagged, routed to the Review queue."""
    return TrackResult(
        source_url=track.source_url,
        tags=None,
        output_path=None,
        status="review",
        reason=reason,
    )
