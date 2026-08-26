"""Ticket #63: space Shazam calls and retry failures, without serialising the batch.

``RateLimitedFingerprinter`` wraps a Fingerprinter so a ~400-Track batch can't
fire hundreds of rapid ``recognize`` calls from one IP. Unlike
``RateLimitedAuthority`` (MusicBrainz wants full serialisation), it spaces call
*starts* and lets the calls themselves overlap — the pipeline is speed-sensitive,
and capping the request rate is what keeps Shazam happy, not serialising the pool.
A failure is retried with backoff a bounded number of times, then degrades to a
miss (``None``) so the batch never blocks; a genuine miss is never retried.

The timing tests follow test_authority_rate_limit.py: small intervals, invariants
(spacing, overlap) rather than wall-clock rates. The retry tests inject ``sleep``
with a zero interval so they are instant and deterministic.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from muzik.domain import Match, Track
from muzik.real.fingerprinter import RateLimitedFingerprinter, ShazamFingerprinter

_INTERVAL = 0.05

_MATCH = Match(title="Envy", artist="Ogi", album="Monologues", confidence=1.0)


def _track(n: int = 0) -> Track:
    return Track(source_url=f"https://youtu.be/{n}", audio_path=Path(f"/fake/{n}.m4a"))


class _RecordingFingerprinter:
    """Records call starts and in-flight overlap; optionally fails the first N calls."""

    def __init__(
        self,
        match: Match | None = _MATCH,
        *,
        work: float = 0.0,
        failures: int = 0,
    ) -> None:
        self._match = match
        self._work = work
        self._failures = failures
        self.calls = 0
        self.starts: list[float] = []
        self._in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def identify(self, track: Track) -> Match | None:
        with self._lock:
            self.calls += 1
            self.starts.append(time.monotonic())
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            failing = self.calls <= self._failures
        try:
            if self._work:
                time.sleep(self._work)
            if failing:
                raise ConnectionError("simulated Shazam failure")
            return self._match
        finally:
            with self._lock:
                self._in_flight -= 1


# --- spacing -------------------------------------------------------------------


def test_concurrent_identify_starts_are_spaced():
    inner = _RecordingFingerprinter(work=_INTERVAL / 5)
    limited = RateLimitedFingerprinter(inner, min_interval=_INTERVAL)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: limited.identify(_track(n)), range(8)))

    starts = sorted(inner.starts)
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert all(gap >= _INTERVAL * 0.9 for gap in gaps), gaps


def test_calls_overlap_rather_than_serialise():
    # The throttle spaces *starts*; it must not hold a lock across the call —
    # that would serialise identification and cost real wall-clock (#63 scope).
    inner = _RecordingFingerprinter(work=0.12)
    limited = RateLimitedFingerprinter(inner, min_interval=0.02)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: limited.identify(_track(n)), range(4)))

    assert inner.max_in_flight >= 2


def test_a_lone_identify_pays_no_wait():
    inner = _RecordingFingerprinter()
    limited = RateLimitedFingerprinter(inner, min_interval=10.0)

    start = time.monotonic()
    assert limited.identify(_track()) == _MATCH
    assert time.monotonic() - start < 1.0


# --- retry ---------------------------------------------------------------------


def test_a_failure_is_retried_with_backoff_then_succeeds():
    sleeps: list[float] = []
    inner = _RecordingFingerprinter(failures=2)
    limited = RateLimitedFingerprinter(
        inner, min_interval=0.0, attempts=3, backoff=2.0, sleep=sleeps.append
    )

    assert limited.identify(_track()) == _MATCH
    assert inner.calls == 3
    assert sleeps == [2.0, 4.0]  # doubling backoff between attempts


def test_exhausted_retries_degrade_to_a_miss_but_say_so(capsys):
    # After the last attempt the wrapper returns None — the miss path the engine
    # already handles (best-effort Tags + Review) — rather than raising. Not
    # silently, though: the Review entry will read as an ordinary miss, so the
    # printed note is the only trace a rate-limited batch leaves.
    inner = _RecordingFingerprinter(failures=99)
    limited = RateLimitedFingerprinter(
        inner, min_interval=0.0, attempts=3, backoff=2.0, sleep=lambda _s: None
    )

    assert limited.identify(_track()) is None
    assert inner.calls == 3
    note = capsys.readouterr().out
    assert "failed 3x" in note and "https://youtu.be/0" in note
    assert "ConnectionError" in note


def test_a_genuine_miss_is_not_retried():
    sleeps: list[float] = []
    inner = _RecordingFingerprinter(match=None)
    limited = RateLimitedFingerprinter(
        inner, min_interval=0.0, attempts=3, backoff=2.0, sleep=sleeps.append
    )

    assert limited.identify(_track()) is None
    assert inner.calls == 1  # a miss is an answer, not a failure
    assert sleeps == []


# --- CLI wiring ----------------------------------------------------------------


def test_the_cli_wraps_shazam_in_the_rate_limiter(tmp_path, monkeypatch):
    from muzik.cli import _build_providers
    from muzik.fakes import FakeDownloader
    from muzik.settings import OutputFormat

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
    providers = _build_providers(FakeDownloader(), OutputFormat.M4A, tmp_path)

    assert isinstance(providers.fingerprinter, RateLimitedFingerprinter)
    assert isinstance(providers.fingerprinter.inner, ShazamFingerprinter)


def test_the_cli_wraps_acoustid_only_when_keyed(tmp_path, monkeypatch):
    from muzik.cli import _build_providers
    from muzik.fakes import FakeDownloader
    from muzik.real.acoustid import AcoustIdFingerprinter
    from muzik.settings import OutputFormat

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Keyless: AcoustID self-disables (returns None instantly); throttling that
    # no-op would only add sleeps to the miss path.
    monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
    providers = _build_providers(FakeDownloader(), OutputFormat.M4A, tmp_path)
    assert isinstance(providers.acoustid, AcoustIdFingerprinter)

    # Keyed: the real service gets the same spacing treatment as Shazam.
    monkeypatch.setenv("ACOUSTID_API_KEY", "k")
    providers = _build_providers(FakeDownloader(), OutputFormat.M4A, tmp_path)
    assert isinstance(providers.acoustid, RateLimitedFingerprinter)
    assert isinstance(providers.acoustid.inner, AcoustIdFingerprinter)
