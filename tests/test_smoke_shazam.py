"""Opt-in smoke test against the REAL Shazam service (shazamio) + ffmpeg (#46).

Shazam is the *primary* identifier, yet in the offline suite it is exercised only
through a fake ``ShazamFingerprinter`` — and a fake encodes the author's assumption
about the real service, so it confirms behaviour rather than disproving a wrong
assumption (docs/LEARNINGS.md). That is the exact gap that let the MusicBrainz album
tier ship dead (#45): no offline test could catch it. This drives the real adapter
against real ffmpeg and the live Shazam backend so its contract is checked against
the thing itself.

Like the other smoke tests it is a pre-merge tool, not a CI gate: it **skips**
(never fails) when the toolchain or network is missing. Run with ``pytest -m smoke``.

It needs, any of which absent → skip:
  * ``ffmpeg`` on PATH (the adapter down-converts the clip before fingerprinting),
  * network to the Shazam service,
and a real audio file to fingerprint. Point ``MUZIK_SMOKE_AUDIO`` at one (any music
file ffmpeg can read); with it unset the fingerprint case skips.

The clip is supplied out-of-band (``MUZIK_SMOKE_AUDIO``) rather than committed to the
repo — the same choice the AcoustID sibling makes — because a clip Shazam can
actually *recognise* is copyrighted music this repo can't ship, and a licence-clean
clip (the CC-BY trick ``test_smoke_yt_dlp`` uses) is not in Shazam's catalogue, so it
would only ever return ``None`` and never exercise the Match path. A real song from
the runner's own library is the only fixture that drives the contract this test
exists to check, so the runner brings it.

Assertions are on **shape** — a ``Match`` (or a clean ``None``) with string fields —
never on the identity a live fingerprint returns, so a re-fingerprint upstream can't
flake the run. Since #58 the adapter parses the response through shazamio's
``Serialize``, so on a Match this also asserts the payload-borne fields (album,
ISRC) still *populate*: a mainstream catalogue Match carries both in the recognize
payload itself, so an empty one here means the serializer wiring dropped data the
raw response had. Point ``MUZIK_SMOKE_AUDIO`` at an *album* track accordingly — a
release with no Album row would trip that assertion. Cover art stays shape-only:
it rides a second CDN fetch that deliberately degrades to ``None`` on a network
blip, and a skip-worthy condition must not fail the run.
"""

from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path

import pytest

from muzik.domain import Track
from muzik.real.fingerprinter import ShazamFingerprinter

pytestmark = pytest.mark.smoke


def _skip_reason() -> str | None:
    if shutil.which("ffmpeg") is None:
        return "ffmpeg not on PATH (see docs/DEVELOPMENT.md)"
    try:
        # shazamio talks to amp.shazam.com; a reachable TLS socket is enough to know
        # the network is up without spending an actual recognition request.
        socket.create_connection(("amp.shazam.com", 443), timeout=5).close()
    except OSError:
        return "no network to Shazam"
    return None


@pytest.fixture(autouse=True)
def _require_toolchain() -> None:
    reason = _skip_reason()
    if reason is not None:
        pytest.skip(reason)


def test_smoke_real_fingerprint_returns_a_match_or_clean_none():
    audio = os.environ.get("MUZIK_SMOKE_AUDIO")
    if not audio or not Path(audio).exists():
        pytest.skip("set MUZIK_SMOKE_AUDIO to a real audio file to run this case")

    fp = ShazamFingerprinter()
    match = fp.identify(Track(source_url="https://youtu.be/x", audio_path=Path(audio)))

    # The #46 contract: a Match, or a clean None — never an exception. (Unlike
    # AcoustID, ShazamFingerprinter does NOT swallow a missing audio file into a
    # miss — its ffmpeg step runs with check=True and would raise — so this case
    # only ever feeds it a real file; the missing-file path is not part of Shazam's
    # contract and is deliberately not asserted here.)
    assert match is None or (
        isinstance(match.title, str)
        and isinstance(match.artist, str)
        # ShazamFingerprinter hard-codes confidence=1.0 — Shazam gives a binary
        # match, not a graded score (docs/LEARNINGS.md).
        and match.confidence == 1.0
        # The #58 serializer swap must not drop payload-borne fields the raw
        # response carries (see module docstring). Still shape, not identity —
        # WHICH album/ISRC comes back is never asserted.
        and match.album != ""
        and isinstance(match.isrc, str)
        and match.isrc != ""
        # Cover art rides a separate CDN fetch that degrades to None on any
        # network blip — a skip-worthy condition must not fail the run.
        and (match.cover_art is None or isinstance(match.cover_art, bytes))
    )
