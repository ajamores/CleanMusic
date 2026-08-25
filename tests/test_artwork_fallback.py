"""Artwork fallback (#52): no downloaded Track should ship with no cover art.

Drives the engine end to end with fake providers. The rule is purely additive —
when identification leaves a Track with no ``cover_art`` and the Track names a
thumbnail, the thumbnail is embedded; real album art is never overridden, and a
fetch failure degrades to bare rather than blocking the batch (ADR-0002).
"""

from pathlib import Path

from muzik.domain import Match, Source
from muzik.engine import Providers, run
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeReviewQueue,
    FakeTagWriter,
    FakeThumbnailFetcher,
)

_THUMB = b"\xff\xd8\xff\xe0THUMBNAILBYTES"  # JPEG magic — the tag writer sniffs it


def _providers(
    match: Match | None,
    *,
    writer: FakeTagWriter,
    fetcher: FakeThumbnailFetcher,
    queue: FakeReviewQueue | None = None,
    source_title: str = "Ogi - Envy",
    uploader: str = "",
    thumbnail_url: str = "https://img/thumb.jpg",
) -> Providers:
    return Providers(
        downloader=FakeDownloader(
            title=source_title, uploader=uploader, thumbnail_url=thumbnail_url
        ),
        fingerprinter=FakeFingerprinter(match=match),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=writer,
        review_queue=queue if queue is not None else FakeReviewQueue(),
        thumbnail_fetcher=fetcher,
    )


def _written(writer: FakeTagWriter):
    assert len(writer.written) == 1
    return writer.written[0][1]


def test_thumbnail_fills_tags_that_have_no_cover_art():
    # A verified Match that carries no cover art of its own: the fallback fills it
    # with the video thumbnail so the file is not bare.
    match = Match(title="Envy", artist="Ogi", album="Monologues", cover_art=None)
    writer, fetcher = FakeTagWriter(), FakeThumbnailFetcher(data=_THUMB)

    results = run(Source(url="https://youtu.be/a"), _providers(match, writer=writer, fetcher=fetcher))

    written = _written(writer)
    assert written.cover_art == _THUMB
    assert results[0].tags.cover_art == _THUMB  # the result reports what was written
    assert fetcher.fetch_calls == ["https://img/thumb.jpg"]


def test_real_album_art_is_never_overridden():
    # A confident Match with real cover art: the fallback leaves it untouched and
    # never even fetches the thumbnail.
    match = Match(title="Envy", artist="Ogi", album="Monologues", cover_art=b"REALART")
    writer, fetcher = FakeTagWriter(), FakeThumbnailFetcher(data=_THUMB)

    run(Source(url="https://youtu.be/a"), _providers(match, writer=writer, fetcher=fetcher))

    assert _written(writer).cover_art == b"REALART"
    assert fetcher.fetch_calls == []  # real art present → no fetch


def test_no_fingerprint_match_is_written_with_source_tags_and_thumbnail():
    # The no-match path used to write nothing (a bare Track). Now it writes
    # best-effort Tags from the Source plus the thumbnail, still queued to Review.
    writer, fetcher = FakeTagWriter(), FakeThumbnailFetcher(data=_THUMB)
    queue = FakeReviewQueue()
    providers = _providers(
        None,
        writer=writer,
        fetcher=fetcher,
        queue=queue,
        source_title="Tower of Power - Some Days Were Meant for Rain",
    )

    results = run(Source(url="https://youtu.be/miss"), providers)

    result = results[0]
    assert result.status == "tagged"  # a file was written
    assert result.reason == "no fingerprint match"  # still routed to Review
    assert result.output_path is not None
    written = _written(writer)
    assert written.title == "Some Days Were Meant for Rain"
    assert written.artist == "Tower of Power"
    assert written.verified is False
    assert written.cover_art == _THUMB
    # Enqueued as an unverified guess, carrying the best-effort Tags.
    assert queue.items()[0].tags is not None
    assert queue.items()[0].tags.title == "Some Days Were Meant for Rain"


def test_no_match_with_a_bare_title_uses_the_channel_as_artist():
    # No "Artist - Title" structure in the Source: the whole title is the title and
    # the normalised channel is the artist — still tagged, not bare.
    writer, fetcher = FakeTagWriter(), FakeThumbnailFetcher(data=_THUMB)
    providers = _providers(
        None, writer=writer, fetcher=fetcher, source_title="Heroin Joint", uploader="J Dilla - Topic"
    )

    run(Source(url="https://youtu.be/miss"), providers)

    written = _written(writer)
    assert written.title == "Heroin Joint"
    assert written.artist == "J Dilla"  # "- Topic" stripped
    assert written.cover_art == _THUMB


def test_a_thumbnail_fetch_failure_degrades_to_bare_without_raising():
    # The fetch fails (None): the Track ships bare rather than crashing the batch.
    match = Match(title="Envy", artist="Ogi", album="Monologues", cover_art=None)
    writer, fetcher = FakeTagWriter(), FakeThumbnailFetcher(data=None)

    results = run(Source(url="https://youtu.be/a"), _providers(match, writer=writer, fetcher=fetcher))

    assert _written(writer).cover_art is None
    assert results[0].tags.cover_art is None
    assert fetcher.fetch_calls == ["https://img/thumb.jpg"]  # it tried


def test_no_match_with_no_source_identity_still_writes_nothing():
    # A no-match Track whose Source names no title at all: there is nothing to
    # write, so it stays a bare Review entry (the prior contract, preserved).
    writer, fetcher = FakeTagWriter(), FakeThumbnailFetcher(data=_THUMB)
    queue = FakeReviewQueue()
    providers = _providers(
        None, writer=writer, fetcher=fetcher, queue=queue, source_title="", thumbnail_url=""
    )

    results = run(Source(url="https://youtu.be/miss"), providers)

    assert results[0].tags is None
    assert results[0].output_path is None
    assert results[0].status == "review"
    assert writer.written == []
    assert queue.items()[0].tags is None
