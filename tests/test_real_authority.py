"""Unit tests for the REAL MusicBrainz album tier (``ShazamOwnAuthority``, #45).

The album waterfall's MusicBrainz tier was exercised only through ``FakeAuthority``
elsewhere — a fake that returns a preset album can't disprove the real code's
assumptions about MusicBrainz's payload shape, and it hid #45: the ISRC lookup
returns releases with **no** ``release-group`` key, so the studio-album filter
matched nothing and the tier was inert for every real ISRC.

These tests drive ``canonical_album`` with ``musicbrainzngs`` monkeypatched to
mirror the real two-call shape — ISRC → recording id, then a browse for that
recording's releases *with* their release-groups — and assert on the album the
filter picks. Guarded live by ``tests/test_smoke_musicbrainz.py``.
"""

from __future__ import annotations

import musicbrainzngs
import pytest

from muzik.real.authority import ShazamOwnAuthority


class _MB:
    """Records the calls made to the monkeypatched musicbrainzngs functions."""

    def __init__(self, *, isrc_result=None, browse_result=None):
        self._isrc_result = isrc_result if isrc_result is not None else {}
        self._browse_result = browse_result if browse_result is not None else {}
        self.isrc_calls: list[tuple] = []
        self.browse_calls: list[dict] = []

    def get_recordings_by_isrc(self, isrc, **kwargs):
        self.isrc_calls.append((isrc, kwargs))
        return self._isrc_result

    def browse_releases(self, **kwargs):
        self.browse_calls.append(kwargs)
        return self._browse_result


def _isrc_response(*recording_ids):
    return {
        "isrc": {
            "id": "USSM20301088",
            "recording-list": [{"id": rid, "title": "Some Track"} for rid in recording_ids],
        }
    }


def _release(title, *, primary=None, type_=None, secondary=None, group_title=None):
    group: dict = {}
    if primary is not None:
        group["primary-type"] = primary
    if type_ is not None:
        group["type"] = type_
    if secondary is not None:
        group["secondary-type-list"] = secondary
    if group_title is not None:
        group["title"] = group_title
    release = {"id": "rel-" + title.lower().replace(" ", "-"), "title": title}
    if group:
        release["release-group"] = group
    return release


def _browse_response(*releases):
    return {"release-count": len(releases), "release-list": list(releases)}


@pytest.fixture
def patch_mb(monkeypatch):
    def _install(mb: _MB) -> _MB:
        monkeypatch.setattr(musicbrainzngs, "get_recordings_by_isrc", mb.get_recordings_by_isrc)
        monkeypatch.setattr(musicbrainzngs, "browse_releases", mb.browse_releases)
        return mb

    return _install


def test_returns_the_studio_album_for_an_isrc(patch_mb):
    mb = patch_mb(
        _MB(
            isrc_result=_isrc_response("rec-1"),
            browse_result=_browse_response(
                _release("Thriller", primary="Album", group_title="Thriller"),
            ),
        )
    )

    assert ShazamOwnAuthority().canonical_album("USSM19902991") == "Thriller"

    # The ISRC resolved a recording, then that recording was browsed *with*
    # release-groups — the second lookup #45 requires (the ISRC entity can't
    # include release-groups itself).
    assert mb.isrc_calls[0][0] == "USSM19902991"
    assert mb.browse_calls[0]["recording"] == "rec-1"
    assert "release-groups" in mb.browse_calls[0]["includes"]


def test_skips_non_studio_releases_and_returns_the_studio_album(patch_mb):
    mb = patch_mb(
        _MB(
            isrc_result=_isrc_response("rec-1"),
            browse_result=_browse_response(
                _release("Thriller (Live)", primary="Album", secondary=["Live"]),
                _release("The Essential", primary="Album", secondary=["Compilation"]),
                _release("Thriller", primary="Album", group_title="Thriller"),
            ),
        )
    )

    assert ShazamOwnAuthority().canonical_album("USSM19902991") == "Thriller"


def test_returns_none_when_every_release_has_a_secondary_type(patch_mb):
    mb = patch_mb(
        _MB(
            isrc_result=_isrc_response("rec-1"),
            browse_result=_browse_response(
                _release("Live in Wembley", primary="Album", secondary=["Live"]),
                _release("Greatest Hits", primary="Album", secondary=["Compilation"]),
            ),
        )
    )

    assert ShazamOwnAuthority().canonical_album("USSM19902991") is None


def test_returns_none_and_makes_no_call_without_an_isrc(patch_mb):
    mb = patch_mb(_MB())

    assert ShazamOwnAuthority().canonical_album(None) is None
    assert ShazamOwnAuthority().canonical_album("") is None
    assert mb.isrc_calls == []
    assert mb.browse_calls == []


def test_returns_none_and_never_browses_when_the_isrc_matches_no_recording(patch_mb):
    mb = patch_mb(_MB(isrc_result=_isrc_response()))

    assert ShazamOwnAuthority().canonical_album("USSM19902991") is None
    assert mb.browse_calls == []


def test_skips_an_id_less_recording_instead_of_crashing(patch_mb):
    # The None-on-any-miss contract: a recording payload without an id is a miss,
    # never a KeyError. It should be skipped without a browse.
    mb = patch_mb(
        _MB(isrc_result={"isrc": {"recording-list": [{"title": "No id here"}]}})
    )

    assert ShazamOwnAuthority().canonical_album("USSM19902991") is None
    assert mb.browse_calls == []


def test_returns_none_on_a_webservice_error_in_the_isrc_lookup(patch_mb, monkeypatch):
    def boom(*a, **k):
        raise musicbrainzngs.WebServiceError("500")

    monkeypatch.setattr(musicbrainzngs, "get_recordings_by_isrc", boom)

    assert ShazamOwnAuthority().canonical_album("USSM19902991") is None


def test_returns_none_on_a_webservice_error_in_the_browse(patch_mb, monkeypatch):
    mb = patch_mb(_MB(isrc_result=_isrc_response("rec-1")))

    def boom(*a, **k):
        raise musicbrainzngs.WebServiceError("503")

    monkeypatch.setattr(musicbrainzngs, "browse_releases", boom)

    assert ShazamOwnAuthority().canonical_album("USSM19902991") is None


def test_falls_back_to_the_release_title_when_the_group_has_none(patch_mb):
    patch_mb(
        _MB(
            isrc_result=_isrc_response("rec-1"),
            browse_result=_browse_response(_release("Bad", primary="Album")),
        )
    )

    assert ShazamOwnAuthority().canonical_album("USSM19902991") == "Bad"


def test_accepts_the_legacy_type_key_when_primary_type_is_absent(patch_mb):
    patch_mb(
        _MB(
            isrc_result=_isrc_response("rec-1"),
            browse_result=_browse_response(
                _release("Dangerous", type_="Album", group_title="Dangerous"),
            ),
        )
    )

    assert ShazamOwnAuthority().canonical_album("USSM19902991") == "Dangerous"
