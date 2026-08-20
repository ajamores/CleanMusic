"""The core engine: the single entry point over the five provider seams.

Interface-agnostic (ADR-0001) — it knows nothing about the CLI or a future web
adapter. It takes a Source and returns one TrackResult per downloaded Track.

Skeleton flow (ticket #2): download → fingerprint → tags-from-Match → write.
The Authority is pass-through and the Resolver is unused here; the verified
waterfall and Confidence gate arrive in later tickets (ADR-0002).
"""

from __future__ import annotations

from dataclasses import dataclass

from muzik.domain import Source, TrackResult
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
    """Process a Source end to end, returning one result per Track."""
    results: list[TrackResult] = []
    for track in providers.downloader.download(source):
        match = providers.fingerprinter.identify(track)
        if match is None:
            results.append(
                TrackResult(
                    source_url=track.source_url,
                    tags=None,
                    output_path=None,
                    status="review",
                    reason="no fingerprint match",
                )
            )
            continue
        tags = providers.authority.tags_for(match)
        output_path = providers.tagwriter.write(track, tags)
        results.append(
            TrackResult(
                source_url=track.source_url,
                tags=tags,
                output_path=output_path,
                status="tagged",
            )
        )
    return results
