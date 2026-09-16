"""One run at a time, in a background thread, streamed to SSE subscribers.

This is a personal tool: a second concurrent run would fight the first over the
download manifest, the Review queue (single-writer — its append needs no lock
only because the engine's drain loop is the sole writer, engine.py #64), and the
``.m3u8``. So the manager holds exactly one run and refuses another while it is
active; the finished state stays readable until the next run replaces it.

Progress reaches subscribers through the engine's own seams — ``run(on_result=…)``
for per-Track outcomes (already flushed to disk when the callback fires) and the
Downloader's ``on_event`` for download ticks — buffered into one queue per SSE
subscriber so a slow reader never stalls the run or another reader.
"""

from __future__ import annotations

import queue
import threading

from muzik.domain import Source, Track, TrackResult
from muzik.engine import Providers, run, summarize
from muzik.providers import PlaylistInSingleModeError
from muzik.web import wire

#: A subscriber's buffered events: ``(name, data)`` pairs, or ``None`` — the
#: close sentinel pushed after the terminal "state" event.
_Event = tuple[str, dict] | None


class RunActiveError(Exception):
    """A run was requested while one is already active (409 at the API edge)."""


class RunManager:
    """The single active run: its state, its background thread, its subscribers.

    ``lock`` is public deliberately: the review-decision route holds it across
    its whole clear pass, so a run cannot start mid-decision — the Review queue
    keeps one writer at a time (the 409s in both directions enforce the same
    invariant the CLI gets for free from being one sequential process).
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._subscribers: list[queue.SimpleQueue[_Event]] = []
        self._thread: threading.Thread | None = None
        self.state = "idle"
        self.url: str | None = None
        self.results: list[TrackResult] = []
        self.error: str | None = None
        self._providers: Providers | None = None

    @property
    def active(self) -> bool:
        return self.state == "running"

    def start(self, source: Source, providers: Providers, concurrency: int | None) -> None:
        """Begin a run, or raise ``RunActiveError`` while one is active.

        A finished run's state is discarded here, not on completion: the last
        outcome stays visible to GET /api/runs/current until the next submission.
        """
        with self.lock:
            if self.active:
                raise RunActiveError("a run is already active")
            self.state = "running"
            self.url = source.url
            self.results = []
            self.error = None
            self._providers = providers
            self._thread = threading.Thread(
                target=self._run,
                args=(source, providers, concurrency),
                name="muzik-run",
                daemon=True,
            )
            self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the current run's thread finishes (tests and shutdown)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self, source: Source, providers: Providers, concurrency: int | None) -> None:
        kwargs = {} if concurrency is None else {"concurrency": concurrency}
        try:
            run(source, providers, on_result=self._on_result, **kwargs)
        except PlaylistInSingleModeError as refusal:
            # A bare playlist in single mode downloaded nothing (ADR-0004): a
            # deliberate refusal with a message, not a failure.
            self._finish("refused", str(refusal))
        except Exception as exc:
            self._finish("failed", f"{type(exc).__name__}: {exc}")
        else:
            self._finish("done", None)

    def _on_result(self, track: Track, result: TrackResult) -> None:
        # Invoked on the engine's drain thread, after the Track's Review enqueue
        # and playlist flush — so a "track" event always reports an outcome
        # already on disk (engine.py, the on_result contract).
        with self.lock:
            self.results.append(result)
            self._publish("track", wire.track_result_json(result))

    def on_download_event(self, event: dict) -> None:
        """The Downloader's per-tick hook — forwarded as a "download" SSE event.

        Only the contract's fields are passed through; the hook's extras stay
        adapter-internal so the wire shape can't drift with the Downloader's.
        ``title`` is the Track's resolved YouTube title — the Downloader emits it
        precisely because ``filename`` is an opaque ``%(id)s`` path (downloader.py,
        _emit_event); ``speed`` stays yt-dlp's raw bytes/s — formatting is the UI's.
        """
        with self.lock:
            self._publish(
                "download",
                {key: event.get(key) for key in ("filename", "percent", "speed", "title")},
            )

    def _finish(self, state: str, error: str | None) -> None:
        with self.lock:
            self.state = state
            self.error = error
            self._publish("state", {"state": state})
            # Terminal: close every stream after its state event. Late
            # subscribers get the terminal snapshot instead (see subscribe).
            for subscriber in self._subscribers:
                subscriber.put(None)
            self._subscribers.clear()

    def _publish(self, name: str, data: dict) -> None:
        for subscriber in self._subscribers:
            subscriber.put((name, data))

    def subscribe(self) -> tuple[dict, queue.SimpleQueue[_Event] | None]:
        """The current snapshot, plus an event queue — or None when the run is
        already terminal (the stream then closes after one state event).

        Snapshot and registration happen under the one lock, so no event
        published after the snapshot can be missed by the queue.
        """
        with self.lock:
            snapshot = self._snapshot_locked()
            if self.state in ("idle", "done", "refused", "failed"):
                return snapshot, None
            subscriber: queue.SimpleQueue[_Event] = queue.SimpleQueue()
            self._subscribers.append(subscriber)
            return snapshot, subscriber

    def unsubscribe(self, subscriber: queue.SimpleQueue[_Event]) -> None:
        with self.lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def snapshot(self) -> dict:
        with self.lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict:
        # Downloader skips and the playlist path are read live off the run's own
        # providers — the same objects the CLI reports from — rather than copied
        # at the end, so a mid-run snapshot already shows them accumulating.
        downloader = getattr(self._providers, "downloader", None)
        skipped = [
            {"source_url": source_url, "reason": reason}
            for source_url, reason in getattr(downloader, "skipped", [])
        ]
        # Fakes predate the manifest report and carry no archive_skips (#24).
        archive_skips = [str(url) for url in getattr(downloader, "archive_skips", [])]
        playlist_path = getattr(
            getattr(self._providers, "playlist_writer", None), "last_written", None
        )
        summary = None
        if self.state == "done":
            tally = summarize(self.results, len(skipped))
            summary = {"verified": tally.verified, "queued": tally.queued}
        return {
            "state": self.state,
            "url": self.url,
            "results": [wire.track_result_json(result) for result in self.results],
            "skipped": skipped,
            "archive_skips": archive_skips,
            "playlist_path": str(playlist_path) if playlist_path is not None else None,
            "summary": summary,
            "error": self.error,
        }
