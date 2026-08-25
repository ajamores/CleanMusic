"""Whole-box tests for AcoustID as a second identity witness (#51, ADR-0006).

AcoustID is a second, independent acoustic source fed to the ADR-0006 identity
witness — never a blind fallback. These drive the engine with a fake Shazam, a fake
AcoustID, and a fake Resolver, and assert the four behaviours the ticket names:

  * Shazam miss + AcoustID hit  — coverage rescue, then witnessed like any identity.
  * Both hit, agree             — the witness sees both acoustic claims.
  * Both hit, disagree          — the witness governs; a dissent routes to Review.
  * Both miss                   — Review; nothing is invented.

plus the cost discipline (#38): the corroborated fast path and the contradicted
path consult neither the witness nor AcoustID.
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


def _providers(shazam, acoustid, resolver, source_title, uploader, writer, authority=None):
    return Providers(
        downloader=FakeDownloader(
            audio_path=Path("/fake/audio.m4a"), title=source_title, uploader=uploader
        ),
        fingerprinter=FakeFingerprinter(match=shazam),
        authority=authority if authority is not None else FakeAuthority(),
        resolver=resolver,
        tagwriter=writer,
        acoustid=acoustid,
    )


# --- Shazam miss, AcoustID hit: coverage rescue -------------------------------


def test_shazam_miss_is_rescued_by_acoustid_and_verified_when_the_title_corroborates():
    # Shazam heard nothing; AcoustID did. Its Match becomes the identity and, because
    # the Source's own title backs it on both title and artist, it verifies outright
    # — the same corroborated fast path a Shazam Match takes, so no witness is needed.
    acoustid_match = Match(title="Trouble Man", artist="Marvin Gaye", album="", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")  # would dissent if ever asked
    results = run(
        Source(url="https://youtu.be/rescue"),
        _providers(
            shazam=None,
            acoustid=FakeFingerprinter(match=acoustid_match),
            resolver=resolver,
            source_title="Marvin Gaye - Trouble Man",
            uploader="",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.reason is None
    assert result.tags.title == "Trouble Man"
    assert resolver.witness_calls == []  # corroborated: no AI even on the rescue path


def test_acoustid_rescue_is_witnessed_when_the_title_does_not_corroborate():
    # AcoustID rescues an identity the title echoes but doesn't independently back
    # (the artist rests on the channel). The witness rules — and with Shazam absent
    # there is no *second* acoustic claim, so it sees AcoustID's alone.
    acoustid_match = Match(title="Trouble Man", artist="Marvin Gaye", album="", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    results = run(
        Source(url="https://youtu.be/rescue2"),
        _providers(
            shazam=None,
            acoustid=FakeFingerprinter(match=acoustid_match),
            resolver=resolver,
            source_title="Trouble Man (Official Audio)",
            uploader="Marvin Gaye",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.reason is None
    assert resolver.witness_calls == [acoustid_match]
    assert resolver.witness_second_opinions == [None]  # Shazam missed: no second source


def test_acoustid_rescue_goes_to_review_when_the_witness_dissents():
    # The other side of the rescue: the witness rules the rescued identity
    # inconsistent, so it is kept unverified and routed to Review.
    acoustid_match = Match(title="Trouble Man", artist="Marvin Gaye", album="", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")
    results = run(
        Source(url="https://youtu.be/rescue3"),
        _providers(
            shazam=None,
            acoustid=FakeFingerprinter(match=acoustid_match),
            resolver=resolver,
            source_title="Trouble Man (Official Audio)",
            uploader="Marvin Gaye",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is False
    assert result.reason is not None
    assert resolver.witness_calls == [acoustid_match]


# --- Album hydration: MusicBrainz by recording id, primary only ---------------


def test_acoustid_rescue_hydrates_its_album_from_the_recording_id():
    # AcoustID gives a MusicBrainz recording id, not an album. On the rescue path it
    # is the primary Match, so it runs the album waterfall — which hydrates the album
    # from that recording id (#45's tier, by recording rather than ISRC).
    acoustid_match = Match(
        title="Trouble Man", artist="Marvin Gaye", album="", recording_mbid="rec-tm", confidence=1.0
    )
    writer = FakeTagWriter()
    authority = FakeAuthority(recording_album="Trouble Man (Original Soundtrack)")
    results = run(
        Source(url="https://youtu.be/album"),
        _providers(
            shazam=None,
            acoustid=FakeFingerprinter(match=acoustid_match),
            resolver=FakeResolver(verdict="consistent"),
            source_title="Marvin Gaye - Trouble Man",  # corroborates → verified
            uploader="",
            writer=writer,
            authority=authority,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.verified is True
    assert result.tags.album == "Trouble Man (Original Soundtrack)"
    assert authority.canonical_album_for_recording_calls == ["rec-tm"]


def test_second_opinion_never_triggers_an_album_lookup():
    # Cost discipline (#38): the second opinion is read by the witness for its
    # title/artist and then discarded — it must never reach the album waterfall, so
    # its recording id costs no MusicBrainz round-trip. Only the primary (Shazam)
    # Match is tagged, and it hydrates by its own ISRC, not the second opinion's id.
    shazam = Match(title="Trouble Man", artist="Marvin Gaye", album="Trouble Man", confidence=1.0)
    acoustid_match = Match(
        title="Trouble Man", artist="Marvin Gaye", album="", recording_mbid="rec-tm", confidence=1.0
    )
    writer = FakeTagWriter()
    authority = FakeAuthority(recording_album="SHOULD-NOT-BE-FETCHED")
    results = run(
        Source(url="https://youtu.be/second"),
        _providers(
            shazam=shazam,
            acoustid=FakeFingerprinter(match=acoustid_match),
            resolver=FakeResolver(verdict="consistent"),
            source_title="Trouble Man (Official Audio)",  # uncorroborated → witness runs
            uploader="Marvin Gaye",
            writer=writer,
            authority=authority,
        ),
    )

    assert results[0].tags is not None and results[0].tags.verified is True
    # The second opinion's recording id was never album-looked-up.
    assert authority.canonical_album_for_recording_calls == []


# --- Both miss: nothing is invented -------------------------------------------


def test_both_fingerprinters_miss_routes_to_review():
    # Neither acoustic source identified the Track. The AI cannot invent an identity
    # from a thumbnail — best-effort Source Tags (#52) and a place in Review.
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    acoustid = FakeFingerprinter(match=None)
    results = run(
        Source(url="https://youtu.be/void"),
        _providers(
            shazam=None,
            acoustid=acoustid,
            resolver=resolver,
            source_title="Trouble Man",
            uploader="Marvin Gaye",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.reason == "no fingerprint match"
    assert result.tags is not None and result.tags.verified is False
    assert len(acoustid.calls) == 1  # AcoustID was tried before giving up
    assert resolver.witness_calls == []  # no Match to witness


# --- Both hit: the witness weighs two acoustic claims -------------------------


def test_both_hit_and_agree_witness_receives_both_acoustic_claims():
    # Shazam is primary; AcoustID is the second opinion. On the uncorroborated path
    # the witness is handed BOTH acoustic identifications — two sources agreeing is
    # stronger than the video's own channel.
    shazam = Match(title="Trouble Man", artist="Marvin Gaye", album="Trouble Man", confidence=1.0)
    acoustid_match = Match(title="Trouble Man", artist="Marvin Gaye", album="", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    acoustid = FakeFingerprinter(match=acoustid_match)
    results = run(
        Source(url="https://youtu.be/agree"),
        _providers(
            shazam=shazam,
            acoustid=acoustid,
            resolver=resolver,
            source_title="Trouble Man (Official Audio)",
            uploader="Marvin Gaye",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.verified is True
    assert resolver.witness_calls == [shazam]  # Shazam stays the identity that verifies
    assert resolver.witness_second_opinions == [acoustid_match]
    assert len(acoustid.calls) == 1


def test_both_hit_but_disagree_and_the_witness_dissents_routes_to_review():
    # The two acoustic sources disagree. The witness — seeing both claims and the
    # video evidence — breaks the tie against verification: kept unverified, Review.
    # The Shazam identity is never silently swapped for AcoustID's (not a fallback).
    shazam = Match(title="Trouble Man", artist="Marvin Gaye", album="Trouble Man", confidence=1.0)
    acoustid_match = Match(title="Some Other Song", artist="Another Artist", album="", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")
    acoustid = FakeFingerprinter(match=acoustid_match)
    results = run(
        Source(url="https://youtu.be/disagree"),
        _providers(
            shazam=shazam,
            acoustid=acoustid,
            resolver=resolver,
            source_title="Trouble Man (Official Audio)",
            uploader="Marvin Gaye",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.verified is False
    assert result.reason is not None
    assert resolver.witness_calls == [shazam]
    assert resolver.witness_second_opinions == [acoustid_match]


# --- Cost discipline (#38): the second source stays off the cheap paths -------


def test_corroborated_fast_path_never_consults_acoustid():
    # The common case: the Source title backs the Shazam Match on title AND artist.
    # It verifies with no AI and — the #51 addition — no second fingerprint either.
    shazam = Match(title="Envy", artist="Ogi", album="Monologues", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")
    acoustid = FakeFingerprinter(match=Match(title="X", artist="Y", album="", confidence=1.0))
    results = run(
        Source(url="https://youtu.be/fast"),
        _providers(
            shazam=shazam,
            acoustid=acoustid,
            resolver=resolver,
            source_title="Ogi - Envy (Official Video)",
            uploader="",
            writer=writer,
        ),
    )

    assert results[0].tags is not None and results[0].tags.verified is True
    assert resolver.witness_calls == []
    assert acoustid.calls == []  # the fast path pays nothing for the second source


def test_title_contradiction_never_consults_acoustid():
    # A Source title that names a *different* recording is a real contradiction: the
    # Track is kept provisional with no AI and no second fingerprint — AcoustID runs
    # only where the witness does (the uncorroborated path), not here.
    shazam = Match(title="Trouble Man", artist="Marvin Gaye", album="Trouble Man", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    acoustid = FakeFingerprinter(match=Match(title="X", artist="Y", album="", confidence=1.0))
    results = run(
        Source(url="https://youtu.be/contradict"),
        _providers(
            shazam=shazam,
            acoustid=acoustid,
            resolver=resolver,
            source_title="Weird Al - Some Parody",
            uploader="",
            writer=writer,
        ),
    )

    assert results[0].tags is not None and results[0].tags.verified is False
    assert results[0].reason is not None
    assert resolver.witness_calls == []
    assert acoustid.calls == []
