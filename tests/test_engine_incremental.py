"""Ticket #64: Review-queue entries and the .m3u8 are written incrementally,
as each Track finishes — an interrupted batch keeps every finished Track's outcome.

Whole-box style (test_engine.py): the engine entry driven with fakes, plus the REAL
M3U8 writer where the on-disk playlist is the assertion. The interrupt is modelled
in-process as a provider raising KeyboardInterrupt mid-batch (the guard, #62,
deliberately passes BaseException through) — the observable proxy for the #66
incident, where a wedged Shazam plus a kill cost the whole batch's end-written
queue and playlist.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from muzik.domain import Match, Source, Track
from muzik.engine import Providers, run
from muzik.fakes import FakeAuthority, FakeResolver, FakeReviewQueue, FakeTagWriter
from muzik.real.playlist import M3u8PlaylistWriter


class _PlaylistDownloader:
    """Canned Tracks plus a playlist title — a --playlist expansion in miniature."""

    def __init__(self, tracks: Sequence[Track], playlist_title: str | None):
        self._tracks = list(tracks)
        self.skipped: list[tuple[str, str]] = []
        self.playlist_title = playlist_title

    def download(self, source: Source) -> list[Track]:
        return list(self._tracks)


class _TarpitFingerprinter:
    """Identifies every Track until the tarpit title, where it aborts the batch.

    KeyboardInterrupt is a BaseException, so it escapes the per-Track guard (#62)
    exactly as a real Ctrl+C on a wedged provider does. The Match it returns never
    agrees with any Source title, so every finished Track takes the provisional
    path — tagged best-effort AND enqueued for Review, exercising both outcomes.
    """

    def __init__(self, tarpit_title: str):
        self._tarpit_title = tarpit_title

    def identify(self, track: Track) -> Match:
        if track.source_title == self._tarpit_title:
            raise KeyboardInterrupt
        return Match(title="Zzz", artist="Nobody", album="", confidence=1.0)


def _track(out_dir, stem: str, title: str, duration: int) -> Track:
    return Track(
        source_url=f"https://youtu.be/{stem}",
        audio_path=out_dir / f"{stem}.m4a",
        source_title=title,
        duration=duration,
    )


def _providers(downloader, queue, playlist_writer=None) -> Providers:
    kwargs = {} if playlist_writer is None else {"playlist_writer": playlist_writer}
    return Providers(
        downloader=downloader,
        fingerprinter=_TarpitFingerprinter(tarpit_title="Wedged - Song"),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=FakeTagWriter(),
        review_queue=queue,
        **kwargs,
    )


def _tarpitted_tracks(out_dir) -> list[Track]:
    """Two Tracks that finish (provisional → queued), then the one that wedges."""
    return [
        _track(out_dir, "a", "Ogi - Envy", 201),
        _track(out_dir, "b", "Adele - Hello", 295),
        _track(out_dir, "c", "Wedged - Song", 180),
    ]


# Both interrupt tests run serial AND concurrent: the in-order drain flushes every
# Track before the wedge regardless of which worker finished first, so the
# assertions hold deterministically even at concurrency 3 (workers may complete
# out of order — including the wedge completing first — but a's and b's results
# are always drained, and flushed, before c's exception is raised).


@pytest.mark.parametrize("concurrency", [1, 3])
def test_an_interrupted_batch_keeps_finished_tracks_review_entries(tmp_path, concurrency):
    # a's and b's Review entries must already be in the queue — in playlist order,
    # the single-writer drain's contract — when the batch dies at c.
    queue = FakeReviewQueue()
    downloader = _PlaylistDownloader(_tarpitted_tracks(tmp_path), playlist_title=None)

    with pytest.raises(KeyboardInterrupt):
        run(
            Source(url="https://youtube.com/playlist?list=PL"),
            _providers(downloader, queue),
            concurrency=concurrency,
        )

    assert [item.source_url for item in queue.items()] == [
        "https://youtu.be/a",
        "https://youtu.be/b",
    ]


@pytest.mark.parametrize("concurrency", [1, 3])
def test_an_interrupted_batch_keeps_the_playlist_written_so_far(tmp_path, concurrency):
    # The .m3u8 on disk — the REAL writer — must already hold the finished Tracks
    # when the batch dies, and never the one that wedged.
    queue = FakeReviewQueue()
    downloader = _PlaylistDownloader(_tarpitted_tracks(tmp_path), playlist_title="Aug 2026")

    with pytest.raises(KeyboardInterrupt):
        run(
            Source(url="https://youtube.com/playlist?list=PL"),
            _providers(downloader, queue, playlist_writer=M3u8PlaylistWriter(tmp_path)),
            concurrency=concurrency,
        )

    body = (tmp_path / "Aug 2026.m3u8").read_text(encoding="utf-8")
    assert "a.m4a" in body and "b.m4a" in body
    assert "c.m4a" not in body


def test_a_completed_batch_still_writes_the_playlist_once_final(tmp_path):
    # Sanity on the happy path: incremental writes must not distort the final list —
    # exact content, in order, matching what the end-written batch produced before.
    queue = FakeReviewQueue()
    tracks = [
        _track(tmp_path, "a", "Ogi - Envy", 201),
        _track(tmp_path, "b", "Adele - Hello", 295),
    ]
    downloader = _PlaylistDownloader(tracks, playlist_title="Aug 2026")

    run(
        Source(url="https://youtube.com/playlist?list=PL"),
        _providers(downloader, queue, playlist_writer=M3u8PlaylistWriter(tmp_path)),
        concurrency=1,
    )

    assert (tmp_path / "Aug 2026.m3u8").read_text(encoding="utf-8") == (
        "#EXTM3U\n"
        "#EXTINF:201,Ogi - Envy\n"
        "a.m4a\n"
        "#EXTINF:295,Adele - Hello\n"
        "b.m4a\n"
    )
