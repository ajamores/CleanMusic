"""Opt-in smoke test against the REAL MusicBrainz web service (#45).

The MusicBrainz album tier was inert for every real ISRC and nothing caught it:
the tier ran only through ``FakeAuthority`` in the offline suite, and a fake that
returns a preset album can't disprove the real code's assumption about the
payload. This test drives ``ShazamOwnAuthority.canonical_album`` against the live
service so a fake can never again make the dead tier look alive.

Like the yt-dlp smoke test it is a pre-merge tool, not a CI gate: it **skips**
(never fails) when there's no network to MusicBrainz. Run with ``pytest -m smoke``.

The ISRCs and their expected studio albums are the four from the #45 report,
verified against the live service. If MusicBrainz re-titles a release-group the
expectation is a one-line fix here — the same trade the yt-dlp fixtures make.
"""

from __future__ import annotations

import socket

import pytest

from muzik.real.authority import ShazamOwnAuthority

pytestmark = pytest.mark.smoke

# ISRC → expected canonical studio album (the #45 report's four tracks).
_CASES = [
    ("USSM20301088", "Thriller"),          # Billie Jean
    ("USUM71900764", "WHEN WE ALL FALL ASLEEP, WHERE DO WE GO?"),  # Bad Guy
    ("USSM19902991", "Thriller"),          # Thriller
    ("USUG12000658", "After Hours"),       # Blinding Lights
]


def _skip_reason() -> str | None:
    try:
        socket.create_connection(("musicbrainz.org", 443), timeout=5).close()
    except OSError:
        return "no network to MusicBrainz"
    return None


@pytest.fixture(autouse=True)
def _require_network() -> None:
    reason = _skip_reason()
    if reason is not None:
        pytest.skip(reason)


@pytest.mark.parametrize("isrc, expected_album", _CASES)
def test_smoke_canonical_album_resolves_the_studio_album(isrc, expected_album):
    # The regression #45 masked: this returned None for every one of these ISRCs.
    assert ShazamOwnAuthority().canonical_album(isrc) == expected_album
