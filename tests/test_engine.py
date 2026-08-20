"""Whole-box ('ignition') tests: drive the engine entry with fake providers."""

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


def _providers(
    match: Match | None,
    tag_writer: FakeTagWriter,
    source_title: str = "Fake Video",
) -> Providers:
    return Providers(
        # The Source's own title is what the Confidence gate cross-checks the
        # Match against; drive it per-test via the fake Downloader's title.
        downloader=FakeDownloader(audio_path=Path("/fake/audio.m4a"), title=source_title),
        fingerprinter=FakeFingerprinter(match=match),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=tag_writer,
    )


def test_happy_path_tags_come_from_the_fingerprinter():
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Monologues",
        cover_art=b"JPEGBYTES",
        confidence=0.99,
    )
    writer = FakeTagWriter()
    results = run(Source(url="https://youtu.be/abc"), _providers(match, writer))

    assert len(results) == 1
    result = results[0]
    assert result.status == "tagged"
    assert result.output_path is not None
    assert result.tags is not None
    # Tags carry the Fingerprinter's own identity + art.
    assert result.tags.title == "Envy"
    assert result.tags.artist == "Ogi"
    assert result.tags.album == "Monologues"
    assert result.tags.cover_art == b"JPEGBYTES"
    # The writer actually received those Tags.
    assert writer.written[0][1].title == "Envy"


def test_confidence_gate_verifies_a_match_that_agrees_with_the_source_title():
    # The Source's own title echoes the Match ("Envy" appears in it), so the
    # gate confirms it: verified Tags, straight from the Match, no marker.
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Monologues",
        cover_art=b"JPEGBYTES",
        confidence=0.99,
    )
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/abc"),
        _providers(match, writer, source_title="Ogi - Envy (Official Video)"),
    )

    result = results[0]
    assert result.status == "tagged"
    assert result.tags is not None
    # Confirmed → verified, and the Match's own identity is written.
    assert result.tags.verified is True
    assert result.tags.title == "Envy"
    assert result.tags.artist == "Ogi"
    assert result.tags.album == "Monologues"
    assert result.tags.cover_art == b"JPEGBYTES"
    # The writer received the verified Tags.
    assert writer.written[0][1].verified is True
    assert writer.written[0][1].title == "Envy"


def test_confidence_gate_writes_provisional_when_the_match_disagrees():
    # A confident Match whose title the Source contradicts must NOT be written
    # as truth. The Source names a different "Artist - Title"; the gate writes
    # that, best-effort and unverified, instead of the wrong Match.
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Monologues",
        cover_art=b"JPEGBYTES",
        confidence=0.99,
    )
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/xyz"),
        _providers(
            match, writer, source_title="Rick Astley - Never Gonna Give You Up"
        ),
    )

    result = results[0]
    assert result.tags is not None
    # The confident-wrong Match is NOT written as verified.
    assert result.tags.verified is False
    assert result.tags.title != "Envy"
    assert result.tags.artist != "Ogi"
    # Provisional Tags are parsed from the Source ("Artist - Title").
    assert result.tags.artist == "Rick Astley"
    assert result.tags.title == "Never Gonna Give You Up"
    # The Match's cover art is not carried onto an unverified Track.
    assert result.tags.cover_art is None
    # The writer received the provisional, unverified Tags — never the Match's.
    assert writer.written[0][1].verified is False
    assert writer.written[0][1].title == "Never Gonna Give You Up"


def test_confidence_gate_falls_back_to_the_uploader_for_a_titleless_artist():
    # When the Source title has no artist before the dash, the parser falls
    # back to the uploader. The current Track model carries no separate
    # uploader field (Track must not be modified for this ticket), so the
    # fallback resolves to an empty artist — pending review — while the title
    # is still recovered from the Source.
    match = Match(title="Envy", artist="Ogi", album="Monologues", confidence=0.99)
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/nnn"),
        _providers(match, writer, source_title=" - Never Gonna Give You Up"),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is False
    assert result.tags.title == "Never Gonna Give You Up"
    assert result.tags.artist == ""


def test_no_match_routes_to_the_review_queue():
    writer = FakeTagWriter()
    results = run(Source(url="https://youtu.be/xyz"), _providers(None, writer))

    assert len(results) == 1
    result = results[0]
    assert result.tags is None
    assert result.output_path is None
    assert result.status == "review"
    assert result.reason == "no fingerprint match"
    # Nothing was written for an unidentified Track.
    assert writer.written == []
