"""Whole-box tests for the Resolver-as-identity-witness gate (#38, ADR-0006).

The Confidence gate no longer trusts Shazam alone on the uncorroborated path.
When the Source title echoes the Match but names no artist of its own — the
uploader-only / no-signal cases where the retired confidence bar sat — the gate
consults the Resolver's identity verdict over the full evidence. These drive the
engine with a fake Resolver and assert the verdict governs the outcome, that the
fast (corroborated) path never calls it, and that a witness failure degrades to
Review rather than aborting the batch.
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


def _providers(match, writer, source_title, uploader, resolver, authority=None):
    return Providers(
        downloader=FakeDownloader(
            audio_path=Path("/fake/audio.m4a"), title=source_title, uploader=uploader
        ),
        fingerprinter=FakeFingerprinter(match=match),
        authority=authority if authority is not None else FakeAuthority(),
        resolver=resolver,
        tagwriter=writer,
    )


def test_impersonator_channel_does_not_verify_when_the_witness_dissents():
    # The #16 shape, observed live: a confident Shazam Match ("Trouble Man" by
    # "Marvin Gaye"), a Source title that carries no artist of its own, and a
    # channel *named* after the artist — an impersonator anyone could set up. The
    # witness, reasoning over the full evidence, rules inconsistent → Review.
    match = Match(
        title="Trouble Man", artist="Marvin Gaye", album="Trouble Man", confidence=1.0
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")
    results = run(
        Source(url="https://youtu.be/imp"),
        _providers(match, writer, "Trouble Man", "Marvin Gaye", resolver),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is False
    assert result.reason is not None  # routed to Review
    assert resolver.witness_calls == [match]  # the witness was actually consulted


def test_genuine_artist_channel_verifies_when_the_witness_agrees():
    # The same uploader-only shape, but a genuine artist channel: the witness rules
    # consistent, so the Match verifies. The paired opposite of the impersonator.
    match = Match(
        title="Trouble Man", artist="Marvin Gaye", album="Trouble Man", confidence=1.0
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    results = run(
        Source(url="https://youtu.be/gen"),
        _providers(match, writer, "Trouble Man", "Marvin Gaye", resolver),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.reason is None
    assert result.tags.artist == "Marvin Gaye"
    assert resolver.witness_calls == [match]


def test_corroborated_fast_path_never_consults_the_witness():
    # Speed contract (#38): when the Source's own title backs both the title and
    # the artist ("Ogi - Envy"), the Match verifies with NO AI call. A witness that
    # would have dissented is proof it was never asked.
    match = Match(title="Envy", artist="Ogi", album="Monologues", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")
    results = run(
        Source(url="https://youtu.be/fast"),
        _providers(match, writer, "Ogi - Envy (Official Video)", "", resolver),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert resolver.witness_calls == []  # the common case pays nothing for the AI


def test_resolver_album_on_a_title_agreeing_track_is_verified_per_the_witness():
    # The #17 shape: the album came from the Resolver (the catalogs missed and the
    # fingerprint album was non-canonical), and the Track's title agrees. Identity
    # is still uncorroborated (the channel supplies the artist), so the witness
    # governs. A consistent verdict verifies the Track *with* the resolved album.
    match = Match(
        title="Envy", artist="Ogi", album="Envy - Single", isrc=None, confidence=1.0
    )
    writer = FakeTagWriter()
    # album=... exercises the Resolver's album tier; verdict=... its identity tier.
    resolver = FakeResolver(album="Monologues", verdict="consistent")
    results = run(
        Source(url="https://youtu.be/17ok"),
        _providers(
            match,
            writer,
            source_title="Envy (Official Audio)",
            uploader="Ogi",
            resolver=resolver,
            authority=FakeAuthority(studio_album=None),
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.tags.album == "Monologues"  # from the Resolver's album tier
    assert resolver.resolve_calls == [match]  # album tier reached
    assert resolver.witness_calls == [match]  # identity tier reached


def test_resolver_album_on_a_title_agreeing_track_goes_to_review_when_the_witness_dissents():
    # The other side of the #17 shape: same resolved album, but the witness rules
    # the identity inconsistent — the Track is kept unverified and routed to Review,
    # album and all. A hallucinated album on a title-agreeing Track no longer rides
    # through to verified.
    match = Match(
        title="Envy", artist="Ogi", album="Envy - Single", isrc=None, confidence=1.0
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(album="Fabricated Album", verdict="inconsistent")
    results = run(
        Source(url="https://youtu.be/17no"),
        _providers(
            match,
            writer,
            source_title="Envy (Official Audio)",
            uploader="Ogi",
            resolver=resolver,
            authority=FakeAuthority(studio_album=None),
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is False
    assert result.reason is not None
    assert resolver.witness_calls == [match]


def test_a_witness_failure_degrades_to_review_and_never_aborts_the_batch():
    # ADR-0002: a Resolver failure/timeout must not abort the batch. A witness that
    # raises is treated as "unsure" → the Track stays unverified and goes to Review,
    # and run() completes normally.
    match = Match(title="Hello", artist="Adele", album="25", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(witness_raises=True)
    results = run(
        Source(url="https://youtu.be/boom"),
        _providers(match, writer, "Hello (Official Video)", "Adele", resolver),
    )

    assert len(results) == 1
    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is False
    assert result.reason is not None
    # The Match is kept for Review, not lost, and the batch ran to completion.
    assert result.tags.title == "Hello"
