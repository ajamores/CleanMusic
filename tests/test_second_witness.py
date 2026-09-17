"""Whole-box tests for AcoustID as a second identity witness (#51, ADR-0006).

AcoustID is a second, independent acoustic source fed to the ADR-0006 identity
witness — never a blind fallback. These drive the engine with a fake Shazam, a fake
AcoustID, and a fake Resolver, and assert the behaviours its tickets name (#51, #87,
#93):

  * Shazam miss + AcoustID hit  — coverage rescue, then witnessed like any identity.
  * Both hit, agree             — with the title agreeing too, verified in code; no witness.
  * Both hit, disagree          — the witness governs; a dissent routes to Review.
  * Both miss                   — Review; nothing is invented.
  * AcoustID top-score tie (#87) — a tied candidate agreeing with Shazam is the
    second opinion; on a rescue, only the Source may settle the tie, else Review.

plus the cost discipline (#38): the corroborated fast path and the contradicted
path consult neither the witness nor AcoustID.
"""

from dataclasses import replace
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
from muzik.real.resolver import HaikuResolver


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
            source_title="Trouble Man (Official Audio)",  # uncorroborated → AcoustID runs
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


def test_both_hit_and_agree_with_the_title_verifies_without_the_witness():
    # #93: Shazam, AcoustID and the Source title all name the same recording. Three
    # independent claims agreeing is settled in code — the witness samples its
    # answer and must not overrule them (observed: "My 1st Song", consistent 3/10).
    shazam = Match(title="Trouble Man", artist="Marvin Gaye", album="Trouble Man", confidence=1.0)
    acoustid_match = Match(title="Trouble Man", artist="Marvin Gaye", album="", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")  # would reject — must not be asked
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
    assert result.reason is None
    assert result.tags.album == "Trouble Man"  # Shazam stays the identity that is tagged
    assert resolver.witness_calls == []
    assert len(acoustid.calls) == 1


def test_acoustid_naming_the_same_song_by_another_artist_is_still_witnessed():
    # Agreement means the same *recording*: a cover shares the song name, so the
    # three claims don't agree and the witness still rules.
    shazam = Match(title="Trouble Man", artist="Marvin Gaye", album="", confidence=1.0)
    cover = Match(title="Trouble Man", artist="Some Cover Band", album="", confidence=1.0)
    resolver = FakeResolver(verdict="inconsistent")
    results = run(
        Source(url="https://youtu.be/cover"),
        _providers(
            shazam=shazam,
            acoustid=FakeFingerprinter(match=cover),
            resolver=resolver,
            source_title="Trouble Man (Official Audio)",
            uploader="Marvin Gaye",
            writer=FakeTagWriter(),
        ),
    )

    assert results[0].tags is not None and results[0].tags.verified is False
    assert resolver.witness_calls == [shazam]
    assert resolver.witness_second_opinions == [cover]


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


# --- AcoustID top-score tie (#87) ---------------------------------------------

#: One fingerprint, two MusicBrainz recordings at an identical score — the observed
#: `32jRn87z3ts` case: a crowd-sourced mislink listed first, the right recording tied.
_MISLINK = Match(title="Track 10", artist="Stephen King", album="", confidence=1.0)
_RIGHT = Match(title="You’ve Changed", artist="Keyshia Cole", album="", confidence=1.0)


def test_a_tied_acoustid_candidate_that_agrees_with_shazam_is_the_second_opinion():
    # The tie is an ambiguity, not a disagreement: one tied recording agrees with
    # Shazam, so that candidate is the second opinion — not the mislink that happened
    # to be listed first — and with the title agreeing too, the Track verifies without
    # the witness (#93).
    shazam = Match(title="You've Changed", artist="Keyshia Cole", album="", confidence=1.0)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")  # would reject — must not be asked
    results = run(
        Source(url="https://youtu.be/32jRn87z3ts"),
        _providers(
            shazam=shazam,
            acoustid=FakeFingerprinter(match=replace(_MISLINK, tied=(_RIGHT,))),
            resolver=resolver,
            source_title="You've Changed",
            uploader="Keyshia Cole",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.verified is True
    assert resolver.witness_calls == []


def test_a_tied_candidate_agrees_with_shazam_across_accented_artist_spellings():
    # #91, the observed "Song Cry" case: Shazam's "JAŸ-Z" never matched AcoustID's
    # "Jay‐Z", so the tie-break missed the four tied "Song Cry" recordings and the
    # junk top candidate reached the witness as a credible rival. Now the tied
    # "Song Cry" agrees with Shazam and the title, so it verifies with no witness.
    shazam = Match(title="Song Cry", artist="JAŸ-Z", album="", confidence=1.0)
    junk = Match(title="What More Can I Say", artist="Jay‐Z", album="", confidence=1.0)
    right = Match(title="Song Cry", artist="Jay‐Z", album="", confidence=1.0)
    resolver = FakeResolver(verdict="inconsistent")  # would reject — must not be asked
    results = run(
        Source(url="https://youtu.be/songcry"),
        _providers(
            shazam=shazam,
            acoustid=FakeFingerprinter(match=replace(junk, tied=(right,))),
            resolver=resolver,
            source_title="Song Cry",
            uploader="JAY-Z - Topic",
            writer=FakeTagWriter(),
        ),
    )

    assert results[0].tags is not None and results[0].tags.verified is True
    assert resolver.witness_calls == []


def test_a_tie_where_no_candidate_agrees_with_shazam_is_still_a_disagreement():
    shazam = Match(title="You've Changed", artist="Keyshia Cole", album="", confidence=1.0)
    other = Match(title="Other Song", artist="Other Artist", album="", confidence=1.0)
    second = replace(_MISLINK, tied=(other,))
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")
    results = run(
        Source(url="https://youtu.be/tie-disagree"),
        _providers(
            shazam=shazam,
            acoustid=FakeFingerprinter(match=second),
            resolver=resolver,
            source_title="You've Changed",
            uploader="Keyshia Cole",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.verified is False
    assert resolver.witness_second_opinions == [second]  # today's disagreement, unchanged


def test_a_rescue_tie_the_source_cannot_separate_goes_to_review_without_a_pick():
    # Shazam missed, so no primary Match breaks the tie, and the Source title backs
    # neither tied recording. Picking one would be response order dressed as an
    # identity: the Track stays provisional and goes to Review, and no witness is
    # asked to rule on an arbitrary pick.
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")  # would verify the pick if asked
    results = run(
        Source(url="https://youtu.be/rescue-tie"),
        _providers(
            shazam=None,
            acoustid=FakeFingerprinter(match=replace(_MISLINK, tied=(_RIGHT,))),
            resolver=resolver,
            source_title="Untitled upload",
            uploader="",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.verified is False
    assert result.reason is not None and "tied" in result.reason
    assert result.tags.title not in {"Track 10", "You’ve Changed"}
    assert resolver.witness_calls == []


def test_a_rescue_tie_is_settled_by_the_source_title_backing_one_candidate():
    # Shazam missed; the Source title names one of the tied recordings. That is
    # evidence, not response order — the backed candidate becomes the identity and is
    # gated like any rescue (here the uploader-only artist sends it to the witness).
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    results = run(
        Source(url="https://youtu.be/32jRn87z3ts"),
        _providers(
            shazam=None,
            acoustid=FakeFingerprinter(match=replace(_MISLINK, tied=(_RIGHT,))),
            resolver=resolver,
            source_title="You've Changed",
            uploader="Keyshia Cole",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.verified is True
    assert (result.tags.title, result.tags.artist) == ("You’ve Changed", "Keyshia Cole")
    assert resolver.witness_calls == [_RIGHT]


def test_a_rescue_tie_between_copies_of_one_recording_is_no_ambiguity():
    # The same song linked twice (an album and a compilation release): the tied
    # candidates agree on identity, so there is nothing to disambiguate.
    album_copy = Match(title="Trouble Man", artist="Marvin Gaye", album="", recording_mbid="rec-a")
    compilation_copy = replace(album_copy, recording_mbid="rec-b")
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    results = run(
        Source(url="https://youtu.be/rescue-copies"),
        _providers(
            shazam=None,
            acoustid=FakeFingerprinter(match=replace(album_copy, tied=(compilation_copy,))),
            resolver=resolver,
            source_title="Untitled upload",
            uploader="Marvin Gaye",
            writer=writer,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.title == "Trouble Man"
    assert result.reason is None or "tied" not in result.reason


def test_a_rescue_tie_between_a_title_and_its_prefix_is_still_ambiguous():
    # "Love" is not a copy of "Love Song" just because its words are a subset: two
    # distinct recordings, so the tie stays unpicked when the Source can't separate.
    love_song = Match(title="Love Song", artist="Adele", album="", confidence=1.0)
    love = Match(title="Love", artist="Adele", album="", confidence=1.0)
    resolver = FakeResolver(verdict="consistent")
    results = run(
        Source(url="https://youtu.be/rescue-prefix"),
        _providers(
            shazam=None,
            acoustid=FakeFingerprinter(match=replace(love_song, tied=(love,))),
            resolver=resolver,
            source_title="Untitled upload",
            uploader="Adele",
            writer=FakeTagWriter(),
        ),
    )

    result = results[0]
    assert result.reason is not None and "tied" in result.reason
    assert resolver.witness_calls == []


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


# --- Two of three agree: the witness is told (#93) ----------------------------


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _PromptRecordingClient:
    """The Anthropic client surface the witness uses; records each prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.messages = self

    def with_options(self, **kwargs):
        return self

    def create(self, **kwargs):
        content = kwargs["messages"][0]["content"]
        if isinstance(content, list):  # the witness call; the album guess sends a str
            self.prompts.append(next(b["text"] for b in content if b["type"] == "text"))
        return type("Resp", (), {"content": [_Block('{"verdict": "consistent"}')]})()


def test_two_of_three_agreement_reaches_the_witness_prompt():
    # Shazam and the title agree on the song; AcoustID names another recording. The
    # witness still rules, but is told the tally so a sampled false memory doesn't
    # overrule two agreeing claims.
    shazam = Match(title="My 1st Song", artist="JAŸ-Z", album="", confidence=1.0)
    other = Match(title="Encore", artist="Jay‐Z", album="", confidence=1.0)
    client = _PromptRecordingClient()
    run(
        Source(url="https://youtu.be/colv2Wy2q7E"),
        _providers(
            shazam=shazam,
            acoustid=FakeFingerprinter(match=other),
            resolver=HaikuResolver(client=client),
            source_title="My 1st Song",
            uploader="JAŸ-Z",
            writer=FakeTagWriter(),
        ),
    )

    assert len(client.prompts) == 1
    assert "Two of three identity sources agree" in client.prompts[0]
    assert "My 1st Song" in client.prompts[0]
    assert "named a different identification" in client.prompts[0]
