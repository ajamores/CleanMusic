"""Whole-box tests for the first tier of the album waterfall (ticket #3, ADR-0002).

Drive the engine entry with fake providers and assert on the album the writer
receives: a canonical fingerprint album is kept without consulting the Authority;
a non-canonical or missing one is replaced by the Authority's studio album by ISRC;
a MusicBrainz miss leaves the album unchanged.
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


def _providers(match, authority, writer):
    return Providers(
        downloader=FakeDownloader(audio_path=Path("/fake/audio.m4a")),
        fingerprinter=FakeFingerprinter(match=match),
        authority=authority,
        resolver=FakeResolver(),
        tagwriter=writer,
    )


def test_canonical_album_is_kept_without_an_authority_lookup():
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Monologues",  # a studio album — already canonical
        isrc="USUG12001234",
        confidence=0.99,
    )
    # The Authority would hand back a different album if asked — it must not be asked.
    authority = FakeAuthority(studio_album="SHOULD NOT BE USED")
    writer = FakeTagWriter()

    results = run(Source(url="https://youtu.be/abc"), _providers(match, authority, writer))

    assert results[0].tags.album == "Monologues"
    assert writer.written[0][1].album == "Monologues"
    # Non-canonical branch never fired, so MusicBrainz was never queried.
    assert authority.canonical_album_calls == []


def test_non_canonical_album_is_replaced_by_the_studio_album():
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Envy - Single",  # non-canonical: a single
        isrc="USUG12001234",
        confidence=0.99,
    )
    authority = FakeAuthority(studio_album="Monologues")
    writer = FakeTagWriter()

    results = run(Source(url="https://youtu.be/abc"), _providers(match, authority, writer))

    assert results[0].tags.album == "Monologues"
    assert writer.written[0][1].album == "Monologues"
    # The Authority was queried by the recording's ISRC.
    assert authority.canonical_album_calls == ["USUG12001234"]


def test_missing_album_triggers_an_authority_lookup():
    match = Match(
        title="Envy",
        artist="Ogi",
        album="",  # missing — treat as non-canonical
        isrc="USUG12001234",
        confidence=0.99,
    )
    authority = FakeAuthority(studio_album="Monologues")
    writer = FakeTagWriter()

    results = run(Source(url="https://youtu.be/abc"), _providers(match, authority, writer))

    assert results[0].tags.album == "Monologues"
    assert authority.canonical_album_calls == ["USUG12001234"]


def test_musicbrainz_miss_leaves_the_album_unchanged():
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Envy - EP",  # non-canonical, so a lookup is attempted
        isrc="USUG12001234",
        confidence=0.99,
    )
    authority = FakeAuthority(studio_album=None)  # MusicBrainz 404 / no studio release
    writer = FakeTagWriter()

    results = run(Source(url="https://youtu.be/abc"), _providers(match, authority, writer))

    assert results[0].status == "tagged"
    assert results[0].tags.album == "Envy - EP"  # unchanged, no crash
    assert authority.canonical_album_calls == ["USUG12001234"]
