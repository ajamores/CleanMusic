"""The two seams a web adapter streams progress through (prep for the FastAPI
adapter; ADR-0001's sibling-adapter framing).

Engine side: ``run(on_result=…)`` must fire once per Track, in drain order, and
only *after* that Track's outcome is flushed (Review enqueue) — so an adapter
never reports an outcome that isn't on disk yet. Downloader side: the yt-dlp
progress hook forwards a best-effort event dict to ``on_event``, and a raising
callback must never break the download — the hook is exercised directly, no
network.
"""

from __future__ import annotations

import pytest

from muzik.domain import Match, Source
from muzik.engine import Providers, run
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeReviewQueue,
    FakeTagWriter,
)
from muzik.real.downloader import YtDlpDownloader


def _providers(queue: FakeReviewQueue) -> Providers:
    # A Match no Source title echoes: every Track takes the provisional path, so
    # each drained result is both written AND enqueued — letting the callback
    # observe the enqueue-before-callback ordering.
    return Providers(
        downloader=FakeDownloader(
            entries=[("Ogi - Envy", False), ("Adele - Hello", False), ("Zed - Three", False)]
        ),
        fingerprinter=FakeFingerprinter(
            Match(title="Zzz", artist="Nobody", album="", confidence=1.0)
        ),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=FakeTagWriter(),
        review_queue=queue,
    )


# Parametrised like the #64 flush tests: the in-order drain makes the callback
# order deterministic even when workers finish out of order.
@pytest.mark.parametrize("concurrency", [1, 3])
def test_on_result_fires_once_per_track_in_drain_order(concurrency):
    queue = FakeReviewQueue()
    seen: list[tuple[str, int]] = []

    def on_result(track, result):
        # Snapshot the queue length: this Track's Review entry must already be
        # enqueued when the callback fires — the flushed-first contract.
        seen.append((track.source_title, len(queue.items())))

    results = run(
        Source(url="https://youtu.be/x"),
        _providers(queue),
        concurrency=concurrency,
        on_result=on_result,
    )

    assert [title for title, _ in seen] == ["Ogi - Envy", "Adele - Hello", "Zed - Three"]
    assert [queued for _, queued in seen] == [1, 2, 3]
    assert len(results) == 3


def test_run_without_on_result_is_unchanged():
    queue = FakeReviewQueue()
    results = run(Source(url="https://youtu.be/x"), _providers(queue))
    assert len(results) == 3
    assert len(queue.items()) == 3


# --- Downloader on_event (hook exercised directly, offline) --------------------


def _tick(video_id: str = "abc123") -> dict:
    """One yt-dlp "downloading" status tick, as the real hook receives it."""
    return {
        "status": "downloading",
        "filename": f"/fake/{video_id}.m4a",
        "downloaded_bytes": 50,
        "total_bytes": 200,
        "speed": 1024.0,
        "info_dict": {"id": video_id, "title": "Ogi - Envy"},
    }


def test_on_event_receives_a_best_effort_progress_dict(tmp_path, capsys):
    events: list[dict] = []
    downloader = YtDlpDownloader(out_dir=tmp_path, on_event=events.append)

    downloader._announce_download(_tick())

    assert events == [
        {
            "filename": "/fake/abc123.m4a",
            "percent": 25.0,
            "speed": 1024.0,
            "title": "Ogi - Envy",
        }
    ]
    # The print announcement is unchanged by the event forwarding.
    assert capsys.readouterr().out == "Ogi - Envy\n"


def test_on_event_fires_every_tick_despite_the_announce_dedup(tmp_path, capsys):
    # The dedup mutes only the second *print*; a streaming adapter still gets
    # the second tick (its percent has moved).
    events: list[dict] = []
    downloader = YtDlpDownloader(out_dir=tmp_path, on_event=events.append)

    downloader._announce_download(_tick())
    second = _tick()
    second["downloaded_bytes"] = 150
    downloader._announce_download(second)

    assert [e["percent"] for e in events] == [25.0, 75.0]
    assert capsys.readouterr().out == "Ogi - Envy\n"


def test_on_event_handles_a_tick_with_no_totals(tmp_path):
    # A live/chunked fetch carries no total_bytes: percent degrades to None
    # rather than raising inside the hook.
    events: list[dict] = []
    downloader = YtDlpDownloader(out_dir=tmp_path, on_event=events.append)
    tick = _tick()
    del tick["total_bytes"]

    downloader._announce_download(tick)

    assert events[0]["percent"] is None


def test_a_raising_on_event_callback_never_breaks_the_download(tmp_path, capsys):
    # A hook exception becomes a yt-dlp error and aborts the fetch (#32), so the
    # guard must swallow the adapter's bug — and the announcement still prints.
    def explode(event: dict) -> None:
        raise RuntimeError("adapter bug")

    downloader = YtDlpDownloader(out_dir=tmp_path, on_event=explode)

    downloader._announce_download(_tick())  # must not raise

    assert capsys.readouterr().out == "Ogi - Envy\n"


def test_no_on_event_leaves_the_hook_print_only(tmp_path, capsys):
    downloader = YtDlpDownloader(out_dir=tmp_path)

    downloader._announce_download(_tick())

    assert capsys.readouterr().out == "Ogi - Envy\n"
