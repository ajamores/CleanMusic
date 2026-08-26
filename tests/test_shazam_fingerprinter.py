"""Unit tests for the real Shazam Fingerprinter's response parsing (#58).

Drives ``_to_match`` — the seam between shazamio's raw ``recognize`` dict and our
``Match`` — with canned payloads shaped like a live capture (2026-08-26, shazamio
0.8.1), so no ffmpeg and no network. Parsing goes through shazamio's own
``Serialize.track`` rather than hand-rolled dict walking; these tests pin the
Match that comes out and that every degraded payload yields empty-string/None
fields — never an exception, and never a whole-Match miss for a single drifted
corner (ADR-0002: the batch never blocks). The live contract itself is covered
by ``test_smoke_shazam``.
"""

from __future__ import annotations

import muzik.real.fingerprinter as fingerprinter
from muzik.real.fingerprinter import _to_match


def _payload(**track_overrides) -> dict:
    """A trimmed live ``recognize`` response; overrides mutate the ``track`` part."""
    track = {
        "key": 5933917,
        "title": "Never Gonna Give You Up",
        "subtitle": "Rick Astley",
        "isrc": "GBARL9300135",
        "images": {
            "coverart": "https://img.example/coverart.jpg",
            "coverarthq": "https://img.example/coverarthq.jpg",
        },
        "sections": [
            {
                "type": "SONG",
                "metapages": [],
                "tabname": "Song",
                "metadata": [
                    {"title": "Album", "text": "Whenever You Need Somebody"},
                    {"title": "Label", "text": "BMG Rights Management (UK) Ltd."},
                    {"title": "Released", "text": "1987"},
                ],
            },
            {"type": "RELATED", "url": "https://cdn.shazam.com/related", "tabname": "Related"},
        ],
    }
    track.update(track_overrides)
    return {
        "matches": [
            {"id": "507112683", "offset": 25.1, "timeskew": -1.7e-05, "frequencyskew": 0.0}
        ],
        "timestamp": 1756215000,
        "timezone": "UTC",
        "tagid": "00000000-0000-0000-0000-000000000000",
        "track": track,
    }


def _stub_fetch(monkeypatch, returning: bytes | None = None) -> list[str | None]:
    """Stub the cover-art download, recording the URL it was asked for."""
    urls: list[str | None] = []

    def fetch(url):
        if not url:  # the real _fetch downloads nothing without a URL
            return None
        urls.append(url)
        return returning

    monkeypatch.setattr(fingerprinter, "_fetch", fetch)
    return urls


def test_full_payload_parses_into_a_match(monkeypatch):
    urls = _stub_fetch(monkeypatch, returning=b"jpeg-bytes")
    match = _to_match(_payload())
    assert match is not None
    assert (match.title, match.artist) == ("Never Gonna Give You Up", "Rick Astley")
    assert match.album == "Whenever You Need Somebody"
    assert match.isrc == "GBARL9300135"
    assert match.cover_art == b"jpeg-bytes"
    assert urls == ["https://img.example/coverarthq.jpg"]  # HQ art preferred
    assert match.confidence == 1.0  # binary: matched or nothing (docs/LEARNINGS.md)


def test_no_match_response_is_a_miss(monkeypatch):
    # Shazam heard nothing it knows: `matches` empty, no `track` key at all.
    _stub_fetch(monkeypatch)
    out = _payload()
    del out["track"]
    out["matches"] = []
    assert _to_match(out) is None


def test_missing_album_row_degrades_to_empty_string(monkeypatch):
    _stub_fetch(monkeypatch)
    sections = [{"type": "SONG", "metapages": [], "tabname": "Song", "metadata": []}]
    match = _to_match(_payload(sections=sections))
    assert match is not None
    assert match.album == ""


def test_missing_sections_degrade_to_empty_album(monkeypatch):
    _stub_fetch(monkeypatch)
    out = _payload()
    del out["track"]["sections"]
    match = _to_match(out)
    assert match is not None
    assert match.album == ""


def test_missing_isrc_degrades_to_none(monkeypatch):
    _stub_fetch(monkeypatch)
    out = _payload()
    del out["track"]["isrc"]
    del out["track"]["sections"]  # no labelled row to fall back to either
    match = _to_match(out)
    assert match is not None
    assert match.isrc is None


def test_isrc_falls_back_to_the_labelled_row(monkeypatch):
    # Some catalogue entries carry the ISRC only as a metadata row, not the named
    # key — the pre-#58 behaviour the swap must keep.
    _stub_fetch(monkeypatch)
    out = _payload()
    del out["track"]["isrc"]
    out["track"]["sections"][0]["metadata"].append({"title": "ISRC", "text": "GBARL8700131"})
    match = _to_match(out)
    assert match is not None
    assert match.isrc == "GBARL8700131"


def test_cover_art_falls_back_to_standard_art_then_none(monkeypatch):
    urls = _stub_fetch(monkeypatch, returning=b"jpeg-bytes")
    match = _to_match(_payload(images={"coverart": "https://img.example/coverart.jpg"}))
    assert match is not None
    assert urls == ["https://img.example/coverart.jpg"]

    out = _payload()
    del out["track"]["images"]
    match = _to_match(out)
    assert match is not None
    assert match.cover_art is None


def test_a_sparse_envelope_does_not_kill_the_match(monkeypatch):
    # Only the `track` part is serialized (Serialize.track, not full_track — see
    # _to_match's docstring), so a missing envelope field cannot zero the Match.
    _stub_fetch(monkeypatch)
    out = _payload()
    del out["tagid"]
    del out["matches"]
    assert _to_match(out) is not None


def test_a_track_the_serializer_rejects_degrades_to_raw_keys(monkeypatch):
    # A SONG section without its metadata rows fails serialization; the Match must
    # keep the raw-keyed title/artist/isrc and drop only the section-borne album —
    # one drifted corner never zeroes the whole Match, and never raises.
    _stub_fetch(monkeypatch)
    out = _payload(sections=[{"type": "SONG", "metapages": [], "tabname": "Song"}])
    match = _to_match(out)
    assert match is not None
    assert (match.title, match.artist) == ("Never Gonna Give You Up", "Rick Astley")
    assert match.album == ""
    assert match.isrc == "GBARL9300135"


def test_a_bare_track_payload_still_degrades_field_by_field(monkeypatch):
    # The pre-#58 behaviour for a track with nothing usable in it: empty-string /
    # None fields, not a miss and not an error.
    _stub_fetch(monkeypatch)
    match = _to_match({"matches": [], "track": {"key": 1}})
    assert match is not None
    assert (match.title, match.artist, match.album) == ("", "", "")
    assert match.isrc is None
    assert match.cover_art is None
