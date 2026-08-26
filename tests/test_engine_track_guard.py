"""Ticket #62: one bad Track must not abort the batch.

The Review queue and the ``.m3u8`` are written only after all processing, so a
mid-batch exception used to lose every result. The engine now guards each Track:
an exception from any stage is captured as that Track's own failed result — the
batch runs to completion, the failure lands in the Review queue with the Track's
identity and the reason, and the playlist skips it. Whole-box style
(test_engine.py): the engine entry driven with fake providers.
"""

from __future__ import annotations

from pathlib import Path

from muzik.domain import Match, PlaylistEntry, Source, Tags, Track
from muzik.engine import Providers, run, summarize
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeReviewQueue,
    FakeTagWriter,
)

_MATCH = Match(title="Envy", artist="Ogi", album="Monologues", confidence=1.0)


class _ExplodingTagWriter:
    """Raises on one Track (by Source title) — a stand-in for a mutagen failure
    on a corrupt/zero-byte file; writes the rest normally."""

    def __init__(self, fail_on_title: str) -> None:
        self._fail_on = fail_on_title
        self.written: list[tuple[Track, Tags]] = []

    def write(self, track: Track, tags: Tags) -> Path:
        if track.source_title == self._fail_on:
            raise OSError("simulated mutagen failure: zero-byte file")
        self.written.append((track, tags))
        return track.audio_path


class _ExplodingFingerprinter:
    """Raises on every Track — a stage failure upstream of the write."""

    def identify(self, track: Track) -> Match | None:
        raise RuntimeError("simulated fingerprint crash")


class _RecordingPlaylistWriter:
    last_written: Path | None = None

    def __init__(self) -> None:
        self.entries: list[PlaylistEntry] | None = None

    def write(self, title: str, entries: list[PlaylistEntry]) -> Path | None:
        self.entries = entries
        return None


def _providers(downloader, queue=None, *, fingerprinter=None, tagwriter=None,
               playlist_writer=None) -> Providers:
    kwargs = {}
    if queue is not None:
        kwargs["review_queue"] = queue
    if playlist_writer is not None:
        kwargs["playlist_writer"] = playlist_writer
    return Providers(
        downloader=downloader,
        fingerprinter=fingerprinter or FakeFingerprinter(match=_MATCH),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=tagwriter or FakeTagWriter(),
        **kwargs,
    )


def test_one_failing_track_does_not_abort_the_batch():
    downloader = FakeDownloader(
        entries=[("Ogi - Envy", False), ("Bad - Apple", False), ("Ogi - Envy", False)]
    )
    tagwriter = _ExplodingTagWriter(fail_on_title="Bad - Apple")
    results = run(Source(url="https://youtu.be/list"), _providers(downloader, tagwriter=tagwriter))

    # Every Track came back, in order — the batch ran to completion.
    assert len(results) == 3
    assert results[0].reason is None and results[2].reason is None
    assert len(tagwriter.written) == 2


def test_a_failed_track_carries_the_failure_as_its_reason():
    downloader = FakeDownloader(entries=[("Bad - Apple", False)])
    tagwriter = _ExplodingTagWriter(fail_on_title="Bad - Apple")
    [result] = run(Source(url="https://youtu.be/x"), _providers(downloader, tagwriter=tagwriter))

    assert result.status == "review"
    assert result.tags is None and result.output_path is None
    # The reason names the exception, so the user can tell a crash from a gate failure.
    assert result.reason is not None
    assert "OSError" in result.reason
    assert "zero-byte file" in result.reason


def test_a_failed_track_is_enqueued_with_its_audio_path():
    queue = FakeReviewQueue()
    downloader = FakeDownloader(entries=[("Ogi - Envy", False), ("Bad - Apple", False)])
    tagwriter = _ExplodingTagWriter(fail_on_title="Bad - Apple")
    run(Source(url="https://youtu.be/list"), _providers(downloader, queue, tagwriter=tagwriter))

    [item] = queue.items()
    assert "OSError" in item.reason
    # The audio file is still on disk; the clear pass needs its path to rescue it.
    assert item.audio_path is not None


def test_a_stage_failure_upstream_of_the_write_is_guarded_too():
    queue = FakeReviewQueue()
    downloader = FakeDownloader(entries=[("Ogi - Envy", False), ("Ogi - Envy", False)])
    providers = _providers(downloader, queue, fingerprinter=_ExplodingFingerprinter())
    results = run(Source(url="https://youtu.be/list"), providers)

    assert len(results) == 2
    assert all(r.status == "review" and r.reason is not None for r in results)
    assert len(queue.items()) == 2
    # The summary counts them as queued, never as verified.
    summary = summarize(results)
    assert (summary.verified, summary.queued) == (0, 2)


def test_a_failed_track_leaves_no_playlist_entry():
    playlist_writer = _RecordingPlaylistWriter()
    downloader = FakeDownloader(entries=[("Ogi - Envy", False), ("Bad - Apple", False)])
    downloader.playlist_title = "August 2026"
    tagwriter = _ExplodingTagWriter(fail_on_title="Bad - Apple")
    run(
        Source(url="https://youtu.be/list"),
        _providers(downloader, tagwriter=tagwriter, playlist_writer=playlist_writer),
    )

    # Only the Track that produced a file is listed — no dead pointer.
    assert playlist_writer.entries is not None
    assert [e.title for e in playlist_writer.entries] == ["Envy"]
