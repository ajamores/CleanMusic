"""Unit tests for the real AcoustID Fingerprinter (#51).

Drives ``AcoustIdFingerprinter`` with an injected ``match_fn`` (standing in for
pyacoustid + fpcalc) — no library, no binary, no network. Checks candidate
selection, the score floor, that the MusicBrainz recording id rides onto the Match
(the album waterfall hydrates the album from it — #45, #51), and that every failure
degrades to a miss (``None``) rather than raising: the batch never blocks (ADR-0002).
"""

from pathlib import Path

from muzik.domain import Track
from muzik.real.acoustid import AcoustIdFingerprinter, _MIN_SCORE

_TRACK = Track(source_url="https://youtu.be/x", audio_path=Path("/fake/clip.m4a"))


def _fp(candidates=None, *, api_key="key", raises=False):
    """An adapter whose fingerprint backend is a canned list, not pyacoustid/fpcalc."""

    def match_fn(_key, _path):
        if raises:
            raise RuntimeError("fpcalc backend missing")
        return list(candidates or [])

    return AcoustIdFingerprinter(api_key=api_key, match_fn=match_fn)


def test_no_api_key_is_a_miss_and_never_fingerprints():
    calls = []

    def match_fn(_key, _path):
        calls.append(_path)
        return []

    fp = AcoustIdFingerprinter(api_key="", match_fn=match_fn)
    assert fp.identify(_TRACK) is None
    assert calls == []  # a missing key short-circuits before any fingerprinting


def test_best_candidate_becomes_a_match_carrying_the_recording_id():
    fp = _fp(candidates=[(0.95, "rec-123", "Billie Jean", "Michael Jackson")])
    match = fp.identify(_TRACK)
    assert match is not None
    assert (match.title, match.artist) == ("Billie Jean", "Michael Jackson")
    assert match.recording_mbid == "rec-123"  # the album waterfall hydrates from this
    assert match.isrc is None  # AcoustID gives a recording id, not an ISRC
    assert match.album == ""  # AcoustID names no album; the waterfall fills it
    assert match.confidence == 1.0  # binary downstream (docs/LEARNINGS.md)


def test_highest_scoring_candidate_wins():
    fp = _fp(
        candidates=[
            (0.6, "rec-low", "Wrong Take", "Someone"),
            (0.9, "rec-high", "Right Take", "The Artist"),
        ]
    )
    match = fp.identify(_TRACK)
    assert match is not None
    assert match.title == "Right Take"
    assert match.recording_mbid == "rec-high"


def test_candidates_below_the_score_floor_are_a_miss():
    fp = _fp(candidates=[(_MIN_SCORE - 0.01, "rec", "Too Weak", "Nobody")])
    assert fp.identify(_TRACK) is None


def test_candidate_without_a_title_is_skipped():
    # AcoustID knows the fingerprint but has no linked recording metadata — nothing
    # to tag or witness, so it is not treated as a match.
    fp = _fp(candidates=[(0.99, "rec", None, "Artist Only")])
    assert fp.identify(_TRACK) is None


def test_no_candidates_is_a_miss():
    assert _fp(candidates=[]).identify(_TRACK) is None


def test_a_backend_error_degrades_to_a_miss():
    # A missing fpcalc or a network error must not raise into the batch.
    assert _fp(raises=True).identify(_TRACK) is None


def test_a_candidate_without_a_recording_id_still_identifies():
    # AcoustID can return a title/artist with no recording id; the identity is still
    # usable (the album just falls to the Resolver tier, having no id to hydrate from).
    fp = _fp(candidates=[(0.95, None, "Song", "Artist")])
    match = fp.identify(_TRACK)
    assert match is not None
    assert match.title == "Song"
    assert match.recording_mbid is None


def test_a_top_score_tie_carries_every_tied_candidate_not_just_the_first_listed():
    # #87: the same fingerprint linked to two recordings at an identical score — a
    # crowd-sourced mislink listed first. A tie is an ambiguity, not a ranking, so the
    # Match carries the other tied candidate for the engine to weigh.
    fp = _fp(
        candidates=[
            (0.9787711, "rec-junk", "Track 10", "Stephen King"),
            (0.9787711, "rec-right", "You’ve Changed", "Keyshia Cole"),
            (0.7, "rec-lower", "Also Ran", "Someone"),
        ]
    )
    match = fp.identify(_TRACK)
    assert match is not None
    identities = {(m.title, m.artist, m.recording_mbid) for m in (match, *match.tied)}
    assert identities == {
        ("Track 10", "Stephen King", "rec-junk"),
        ("You’ve Changed", "Keyshia Cole", "rec-right"),
    }
    assert all(t.tied == () for t in match.tied)


def test_a_clear_winner_carries_no_ties():
    fp = _fp(
        candidates=[
            (0.9, "rec-high", "Right Take", "The Artist"),
            (0.6, "rec-low", "Wrong Take", "Someone"),
        ]
    )
    match = fp.identify(_TRACK)
    assert match is not None and match.tied == ()
