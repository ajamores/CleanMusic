"""Shared builders for the Review-queue clear-pass tests (#7).

Both the engine-level (``test_review_clear``) and CLI-level (``test_cli_review``)
whole-box tests wire the same fake providers around a preloaded queue; this keeps
that wiring in one place.
"""

from __future__ import annotations

from pathlib import Path

from muzik.domain import Match, ReviewItem, Tags
from muzik.engine import Providers
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeReviewQueue,
    FakeTagWriter,
)


def review_providers(
    queue: FakeReviewQueue, writer: FakeTagWriter, *, match: Match | None = None
) -> Providers:
    """Fake providers for a clear pass; the Downloader is unused (a batch already ran)."""
    return Providers(
        downloader=FakeDownloader(),
        fingerprinter=FakeFingerprinter(match=match),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=writer,
        review_queue=queue,
    )


def provisional_item(source_url: str) -> ReviewItem:
    """A gate-failure entry: provisional Tags written to a file, awaiting review."""
    return ReviewItem(
        source_url=source_url,
        reason="unverified: provisional Tags from the Source, Match not corroborated",
        tags=Tags(title="Wrong Title", artist="Wrong Artist", album="", verified=False),
        output_path=Path("/fake/audio.m4a"),
        audio_path=Path("/fake/audio.m4a"),
    )
