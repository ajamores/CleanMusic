"""RateLimitedAuthority (ticket #8): keep MusicBrainz lookups within ~1 req/sec
even when the batch runs Tracks concurrently.

Only ``canonical_album`` hits the network, so only it is throttled; ``tags_for``
is pure and must pass straight through. The tests use a small interval and assert
the two invariants that matter under concurrency — calls never overlap, and
consecutive calls are spaced by at least the interval — rather than a wall-clock
rate, so they stay fast and non-flaky.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from muzik.domain import Match
from muzik.real.authority import RateLimitedAuthority

_INTERVAL = 0.05


class _RecordingAuthority:
    """Records when each ``canonical_album`` call is in flight, to detect overlap."""

    def __init__(self) -> None:
        self.intervals: list[tuple[float, float]] = []
        self._in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()
        self.tags_for_calls = 0

    def tags_for(self, match: Match):
        self.tags_for_calls += 1
        return "tags"

    def canonical_album(self, isrc):
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        start = time.monotonic()
        time.sleep(_INTERVAL / 5)  # a little work, so overlap would be observable
        end = time.monotonic()
        with self._lock:
            self._in_flight -= 1
            self.intervals.append((start, end))
        return "album"


def test_concurrent_lookups_are_serialized_and_spaced():
    inner = _RecordingAuthority()
    authority = RateLimitedAuthority(inner, min_interval=_INTERVAL)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: authority.canonical_album(f"ISRC{n}"), range(8)))

    # Never two MusicBrainz calls in flight at once.
    assert inner.max_in_flight == 1
    # And consecutive calls are spaced by at least the interval.
    starts = sorted(start for start, _ in inner.intervals)
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert all(gap >= _INTERVAL * 0.9 for gap in gaps), gaps


def test_tags_for_is_not_throttled():
    # ``tags_for`` does no I/O; it must bypass the throttle entirely.
    inner = _RecordingAuthority()
    authority = RateLimitedAuthority(inner, min_interval=10.0)

    start = time.monotonic()
    for _ in range(5):
        assert authority.tags_for(Match(title="t", artist="a", album="")) == "tags"
    elapsed = time.monotonic() - start

    assert inner.tags_for_calls == 5
    assert elapsed < 1.0  # would be ~40s if throttled


def test_a_lone_lookup_pays_no_wait():
    # The throttle only spaces *successive* calls; the first pays nothing.
    inner = _RecordingAuthority()
    authority = RateLimitedAuthority(inner, min_interval=10.0)

    start = time.monotonic()
    assert authority.canonical_album("ISRC1") == "album"
    assert time.monotonic() - start < 1.0
