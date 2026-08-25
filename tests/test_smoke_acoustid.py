"""Opt-in smoke test against the REAL AcoustID service + fpcalc (#51, #46).

The offline suite fakes AcoustID's ``match_fn``/``isrc_fn``, and a fake can't
disprove a wrong assumption about the real backend — the exact gap that hid the
dead MusicBrainz tier (#45). This drives ``AcoustIdFingerprinter`` end to end
against real Chromaprint (``fpcalc``) and the live AcoustID web service so the
adapter's contract is checked against the thing itself.

Like the other smoke tests it is a pre-merge tool, not a CI gate: it **skips**
(never fails) when the toolchain or network is missing. Run with ``pytest -m smoke``.

It needs, any of which absent → skip:
  * ``fpcalc`` (Chromaprint) on PATH,
  * an ``ACOUSTID_API_KEY`` in the environment / .env,
  * network to the AcoustID service,
and a real audio file to fingerprint. Point ``MUZIK_SMOKE_AUDIO`` at one (any
music file fpcalc can read); with it unset the fingerprint case skips.
"""

from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path

import pytest

from muzik.domain import Track
from muzik.real.acoustid import AcoustIdFingerprinter

pytestmark = pytest.mark.smoke

load_dotenv = pytest.importorskip("dotenv").load_dotenv


def _skip_reason() -> str | None:
    if shutil.which("fpcalc") is None:
        return "fpcalc (Chromaprint) not on PATH"
    load_dotenv()
    if not os.environ.get("ACOUSTID_API_KEY"):
        return "no ACOUSTID_API_KEY"
    try:
        socket.create_connection(("api.acoustid.org", 443), timeout=5).close()
    except OSError:
        return "no network to AcoustID"
    return None


@pytest.fixture(autouse=True)
def _require_toolchain() -> None:
    reason = _skip_reason()
    if reason is not None:
        pytest.skip(reason)


def test_smoke_missing_audio_file_is_a_miss_not_a_crash():
    # fpcalc can't fingerprint a path that isn't there — the adapter must swallow
    # that into a miss (None), never a raise, so a bad Track never aborts a batch.
    fp = AcoustIdFingerprinter()
    track = Track(source_url="https://youtu.be/x", audio_path=Path("/does/not/exist.m4a"))
    assert fp.identify(track) is None


def test_smoke_real_fingerprint_identifies_a_known_track():
    audio = os.environ.get("MUZIK_SMOKE_AUDIO")
    if not audio or not Path(audio).exists():
        pytest.skip("set MUZIK_SMOKE_AUDIO to a real audio file to run this case")

    fp = AcoustIdFingerprinter()
    match = fp.identify(Track(source_url="https://youtu.be/x", audio_path=Path(audio)))
    # A real music file should identify; we assert the shape, not a specific title
    # (which depends on the fixture the runner supplies). AcoustID returns a
    # MusicBrainz recording id, which the album waterfall later hydrates from (#45).
    assert match is not None
    assert match.title and match.artist
    assert match.confidence == 1.0
