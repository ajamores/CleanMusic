"""The core engine: the single entry point over the five provider seams.

Interface-agnostic (ADR-0001) — it knows nothing about the CLI or a future web
adapter. It takes a Source and returns one TrackResult per downloaded Track.

Flow (ticket #2): download → fingerprint → album waterfall → confidence gate →
write. Each stage is its own function so later tickets extend one seam without
touching the others: #3/#4 grow ``_album_waterfall``, #5 fills ``_confidence_gate``,
#9 grows ``_write``. The skeleton's stages are pass-throughs (ADR-0002).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
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


#: Tokens that mark a fingerprint album as non-canonical (a single / EP / remix)
#: rather than a studio album. Matched against whole words, so "Deep" or "Sleep"
#: don't trip the "ep" marker.
_NON_CANONICAL_MARKERS = frozenset({"single", "ep", "remix", "remixes"})


def _looks_canonical(album: str) -> bool:
    """A studio album, worth keeping as-is? Empty or single/EP/remix albums aren't."""
    if not album or not album.strip():
        return False
    words = set(re.findall(r"[a-z]+", album.lower()))
    return words.isdisjoint(_NON_CANONICAL_MARKERS)


def _album_waterfall(match: Match, providers: Providers) -> Tags:
    """First tier of the album waterfall (ADR-0002, ticket #3).

    Keep the fingerprint's album when it already looks canonical. When it looks
    non-canonical (single / EP / remix) or is missing, ask the Authority for the
    recording's canonical studio album by ISRC and substitute it. A miss (no ISRC,
    or MusicBrainz returns nothing) leaves the album unchanged. #4 adds the
    Resolver tier below this.
    """
    tags = providers.authority.tags_for(match)
    if _looks_canonical(match.album) or not match.isrc:
        return tags
    studio_album = providers.authority.canonical_album(match.isrc)
    if not studio_album:
        return tags
    return replace(tags, album=studio_album)


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
