"""Whole-box tests for the final tier of the album waterfall (ticket #4, ADR-0002).

The Resolver (Claude Haiku) is the last resort: it proposes a studio album only
when neither the Fingerprinter nor the Authority yielded a canonical one. Drive
the engine with a fake Resolver and assert on the album the writer receives, and
on whether the tier was reached at all — it must fire only when the catalogs miss.
"""

from pathlib import Path

from muzik.domain import Match, Source
from muzik.engine import Providers, run
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeTagWriter,
)


def _providers(match, authority, resolver, writer):
    return Providers(
        downloader=FakeDownloader(audio_path=Path("/fake/audio.m4a")),
        fingerprinter=FakeFingerprinter(match=match),
        authority=authority,
        resolver=resolver,
        tagwriter=writer,
    )


def _run(match, authority, resolver, writer):
    return run(
        Source(url="https://youtu.be/abc"),
        _providers(match, authority, resolver, writer),
    )


def test_resolver_supplies_album_when_the_catalogs_miss():
    # Non-canonical fingerprint album, and MusicBrainz has no studio release for
    # the ISRC — the waterfall is still unresolved, so the Resolver is consulted.
    match = Match(
        title="Envy", artist="Ogi", album="Envy - Single",
        isrc="USUG12001234", confidence=0.99,
    )
    authority = FakeAuthority(studio_album=None)  # MusicBrainz miss
    resolver = FakeResolver(album="Monologues")
    writer = FakeTagWriter()

    results = _run(match, authority, resolver, writer)

    assert results[0].tags.album == "Monologues"
    assert writer.written[0][1].album == "Monologues"
    assert authority.canonical_album_calls == ["USUG12001234"]  # MB tried first
    assert resolver.resolve_calls == [match]  # then the Resolver


def test_resolver_is_consulted_when_there_is_no_isrc():
    # No ISRC means MusicBrainz cannot be asked at all — the Resolver is the only
    # tier left below the non-canonical fingerprint album.
    match = Match(title="Envy", artist="Ogi", album="", isrc=None, confidence=0.99)
    authority = FakeAuthority(studio_album="SHOULD NOT BE USED")
    resolver = FakeResolver(album="Monologues")
    writer = FakeTagWriter()

    results = _run(match, authority, resolver, writer)

    assert results[0].tags.album == "Monologues"
    assert authority.canonical_album_calls == []  # no ISRC: MB never queried
    assert resolver.resolve_calls == [match]


def test_resolver_does_not_fire_when_the_fingerprint_album_is_canonical():
    match = Match(
        title="Envy", artist="Ogi", album="Monologues",
        isrc="USUG12001234", confidence=0.99,
    )
    resolver = FakeResolver(album="SHOULD NOT BE USED")
    writer = FakeTagWriter()

    results = _run(match, FakeAuthority(studio_album="X"), resolver, writer)

    assert results[0].tags.album == "Monologues"
    assert resolver.resolve_calls == []  # canonical already — tier never reached


def test_resolver_does_not_fire_when_musicbrainz_resolves_the_album():
    match = Match(
        title="Envy", artist="Ogi", album="Envy - EP",
        isrc="USUG12001234", confidence=0.99,
    )
    resolver = FakeResolver(album="SHOULD NOT BE USED")
    writer = FakeTagWriter()

    results = _run(match, FakeAuthority(studio_album="Monologues"), resolver, writer)

    assert results[0].tags.album == "Monologues"
    assert resolver.resolve_calls == []  # MusicBrainz resolved it — tier not needed


def test_resolver_declining_leaves_the_album_unchanged():
    match = Match(
        title="Envy", artist="Ogi", album="Envy - EP",
        isrc="USUG12001234", confidence=0.99,
    )
    resolver = FakeResolver(album=None)  # the Resolver declines
    writer = FakeTagWriter()

    results = _run(match, FakeAuthority(studio_album=None), resolver, writer)

    assert results[0].status == "tagged"
    assert results[0].tags.album == "Envy - EP"  # unchanged, no crash
    assert resolver.resolve_calls == [match]
