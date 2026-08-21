"""Ticket #8: a playlist Source is expanded into many Tracks, processed
concurrently under a bounded limit, in order, and not re-fetched on a re-run.

Whole-box style (test_engine.py): the engine entry driven with fake providers.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from muzik.domain import Match, Source, Tags, Track
from muzik.engine import Providers, run
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeReviewQueue,
    FakeTagWriter,
)
from muzik.real.authority import RateLimitedAuthority

_MATCH = Match(
    title="Envy", artist="Ogi", album="Monologues", cover_art=b"ART", confidence=0.99
)


def _providers(
    downloader: FakeDownloader,
    queue: FakeReviewQueue | None = None,
    *,
    fingerprinter=None,
    authority=None,
) -> Providers:
    return Providers(
        downloader=downloader,
        fingerprinter=fingerprinter or FakeFingerprinter(match=_MATCH),
        authority=authority or FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=FakeTagWriter(),
        review_queue=queue or FakeReviewQueue(),
    )


# --- AC1 / AC6: one tagged Track per playlist video ----------------------------


def test_a_playlist_produces_one_result_per_video_in_order():
    downloader = FakeDownloader(
        entries=[
            ("Ogi - Envy", False),
            ("Ogi - Envy", False),
            ("Ogi - Envy", False),
        ]
    )
    results = run(Source(url="https://youtu.be/list"), _providers(downloader))

    assert len(results) == 3
    assert all(r.status == "tagged" for r in results)
    assert all(r.tags is not None and r.tags.verified for r in results)


def test_results_stay_in_playlist_order_under_concurrency():
    # Each entry carries a distinct title; the gate parses the title into the
    # provisional artist, so the result order is observable and must match input.
    titles = [f"Artist{n} - Song{n}" for n in range(6)]
    downloader = FakeDownloader(entries=[(t, False) for t in titles])
    # A Match that won't agree with any of these titles → provisional Tags parsed
    # from each Source title, so we can read the per-Track identity back out.
    providers = _providers(
        downloader,
        fingerprinter=FakeFingerprinter(
            match=Match(title="Zzz", artist="Nobody", album="", confidence=0.99)
        ),
    )
    results = run(Source(url="https://youtu.be/list"), providers, concurrency=6)

    assert [r.tags.title for r in results] == [f"Song{n}" for n in range(6)]


# --- AC2: bounded concurrency, faster than serial ------------------------------


class _ConcurrencyProbeFingerprinter:
    """Records the peak number of identify() calls in flight at once."""

    def __init__(self, match: Match, work: float) -> None:
        self._match = match
        self._work = work
        self._in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def identify(self, track: Track) -> Match:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        time.sleep(self._work)
        with self._lock:
            self._in_flight -= 1
        return self._match


def test_tracks_process_concurrently_not_serially():
    probe = _ConcurrencyProbeFingerprinter(_MATCH, work=0.05)
    downloader = FakeDownloader(entries=[("Ogi - Envy", False)] * 8)
    providers = _providers(downloader, fingerprinter=probe)

    start = time.monotonic()
    results = run(Source(url="https://youtu.be/list"), providers, concurrency=4)
    elapsed = time.monotonic() - start

    assert len(results) == 8
    # Genuinely overlapping — more than one Track in flight at a peak.
    assert probe.max_in_flight >= 2
    # And faster than serial (8 * 0.05 = 0.40s); a bound of 4 should land near half.
    assert elapsed < 0.30


def test_concurrency_is_bounded_by_the_limit():
    probe = _ConcurrencyProbeFingerprinter(_MATCH, work=0.03)
    downloader = FakeDownloader(entries=[("Ogi - Envy", False)] * 8)
    providers = _providers(downloader, fingerprinter=probe)

    run(Source(url="https://youtu.be/list"), providers, concurrency=3)

    # Never more Tracks in flight than the bound allows.
    assert probe.max_in_flight <= 3


# --- AC4: re-running the same Source skips already-fetched Tracks ---------------


def test_rerunning_a_source_skips_already_fetched_tracks():
    archive: set[str] = set()
    # Distinct titles stand in for yt-dlp's per-video archive keys (its real
    # archive keys on video id, unique per video).
    entries = [("Ogi - Envy", False), ("Ogi - Rue", False)]

    first = FakeDownloader(entries=entries, download_archive=archive)
    first_results = run(Source(url="https://youtu.be/list"), _providers(first))
    assert len(first_results) == 2  # both fetched and tagged on the first run

    # A second run over the same Source (same archive) re-downloads nothing.
    second = FakeDownloader(entries=entries, download_archive=archive)
    second_results = run(Source(url="https://youtu.be/list"), _providers(second))
    assert second_results == []


# --- AC3: Authority stays within its rate limit through the engine's run -------


class _OverlapProbeAuthority:
    """A whole-box Authority that flags any two ``canonical_album`` calls in flight
    at once — the invariant the rate limiter must hold under the engine's pool."""

    def __init__(self) -> None:
        self._in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def tags_for(self, match: Match) -> Tags:
        return Tags(title=match.title, artist=match.artist, album=match.album)

    def canonical_album(self, isrc):
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        time.sleep(0.005)
        with self._lock:
            self._in_flight -= 1
        return None


def test_authority_stays_within_its_rate_limit_through_a_concurrent_run():
    # End-to-end (not just the wrapper in isolation): a playlist runs concurrently
    # through RateLimitedAuthority, and its MusicBrainz tier must never have two
    # calls in flight. A non-canonical album + an ISRC forces the lookup per Track.
    probe = _OverlapProbeAuthority()
    fingerprinter = FakeFingerprinter(
        match=Match(title="Envy", artist="Ogi", album="", isrc="USABC1234567", confidence=0.99)
    )
    downloader = FakeDownloader(entries=[("Ogi - Envy", False)] * 6)
    providers = _providers(
        downloader,
        fingerprinter=fingerprinter,
        authority=RateLimitedAuthority(probe, min_interval=0.01),
    )

    run(Source(url="https://youtu.be/list"), providers, concurrency=6)

    assert probe.max_in_flight == 1


# --- the batch still fills the Review queue under concurrency ------------------


def test_reviewable_tracks_are_enqueued_once_each_under_concurrency():
    queue = FakeReviewQueue()
    downloader = FakeDownloader(
        entries=[
            ("Ogi - Envy", False),  # agrees → verified, not queued
            ("Someone Else - Other Song", False),  # disagrees → queued
            ("Another - Third", False),  # disagrees → queued
        ]
    )
    results = run(
        Source(url="https://youtu.be/list"), _providers(downloader, queue), concurrency=4
    )

    assert len(results) == 3
    queued = [item.source_url for item in queue.items()]
    assert len(queued) == 2  # exactly the two gate failures, each enqueued once
