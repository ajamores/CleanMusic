"""The FastAPI app over the engine — routes per API CONTRACT v1.

A factory, not a module-level app: the providers-builder is injected (real
wiring, demo fakes, or test fakes), so the routes stay as ignorant of provider
assembly as the CLI is (ADR-0001, ADR-0010). Providers are built fresh per run
and per review pass — the same lifetime a CLI invocation gives them — so no
provider state leaks between runs.
"""

from __future__ import annotations

import json
import queue as queue_module
from pathlib import Path
from typing import Callable, Literal, Protocol

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from pydantic import BaseModel

from muzik.domain import ReviewDecision, ReviewItem, Source, Tags
from muzik.engine import Providers, clear_review_queue
from muzik.settings import OutputFormat, Settings, load_settings, save_settings
from muzik.web import wire
from muzik.web.jobs import RunActiveError, RunManager
from muzik.wiring import FORMAT_CHOICES, resolve_format

#: The API's spelling for each saved format — FORMAT_CHOICES, reversed.
_FORMAT_NAMES = {fmt: name for name, fmt in FORMAT_CHOICES.items()}

FormatName = Literal["m4a", "mp3-320"]


class ProvidersBuilder(Protocol):
    """Assembles the Providers one run (or review pass) uses.

    ``on_event`` is the Downloader's progress hook (None outside a run); the
    real builder threads it into ``wiring.build_downloader``.
    """

    def __call__(
        self,
        fmt: OutputFormat,
        *,
        expand_playlist: bool = False,
        limit: int | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> Providers: ...


class RunRequest(BaseModel):
    url: str
    playlist: bool = False
    limit: int | None = None
    format: FormatName | None = None
    concurrency: int | None = None


class TagsBody(BaseModel):
    title: str
    artist: str
    album: str
    track_number: int | None = None
    year: int | None = None


class DecisionRequest(BaseModel):
    action: Literal["accept", "manual", "hint", "skip"]
    tags: TagsBody | None = None
    hint: str | None = None
    #: The queue is index-addressed but mutable between a listing and a decision;
    #: the URL pins which entry the index was meant for (409 on a mismatch).
    source_url: str


class SettingsBody(BaseModel):
    format: FormatName


class _OneShotPrompter:
    """A ReviewPrompter answering for exactly one queue entry, skip for the rest.

    Decisions go through ``engine.clear_review_queue`` — the same seam the CLI's
    interactive prompter drives — so the queue rewrite and survivor semantics
    stay the engine's; this adapter never edits the queue file itself. A skip
    leaves an entry untouched, so "everything but the target" survives verbatim.
    """

    def __init__(self, index: int, source_url: str, decision: ReviewDecision) -> None:
        self._index = index
        self._source_url = source_url
        self._decision = decision
        self._position = 0

    def decide(self, item: ReviewItem) -> ReviewDecision:
        position = self._position
        self._position += 1
        if position == self._index and item.source_url == self._source_url:
            return self._decision
        return ReviewDecision(action="skip")


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def _audio_media_type(path: Path) -> str:
    # The two formats Muzik writes (settings.py); anything else is a queue record
    # from outside this tool — served, but not claimed as audio.
    return {".m4a": "audio/mp4", ".mp3": "audio/mpeg"}.get(
        path.suffix.lower(), "application/octet-stream"
    )


def _embedded_cover(path: Path | None) -> bytes | None:
    """Cover art read back out of the written Track file.

    The persisted queue deliberately drops ``cover_art`` (review_queue.py):
    the provisionally-written file already holds it. So ``has_cover`` and the
    cover endpoint recover it from the file — the two containers Muzik writes,
    as in ``_audio_media_type``. Any read failure degrades to "no cover".
    """
    if path is None:
        return None
    try:
        suffix = path.suffix.lower()
        if suffix == ".m4a":
            covers = (MP4(path).tags or {}).get("covr") or []
            return bytes(covers[0]) if covers else None
        if suffix == ".mp3":
            for frame in ID3(path).getall("APIC"):
                return frame.data
    except Exception:
        return None
    return None


def _cover_bytes(item: ReviewItem) -> bytes | None:
    # In-memory queues (demo, tests) still carry the bytes on the Tags; the
    # real queue's reloaded records don't, and fall back to the written file.
    if item.tags is not None and item.tags.cover_art is not None:
        return item.tags.cover_art
    return _embedded_cover(item.output_path)


def _sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def create_app(
    providers_builder: ProvidersBuilder,
    out_dir: Path,
    *,
    settings_path: Path | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Assemble the app: API routes first, then the SPA's static files at ``/``.

    ``settings_path`` overrides the saved-settings location (demo and tests
    isolate it; None keeps the user's real settings file). ``static_dir``
    likewise (None serves the packaged SPA).
    """
    app = FastAPI(title="Muzik")
    manager = RunManager()
    #: Exposed for tests: joining the run thread beats polling for a state.
    app.state.manager = manager

    def _review_providers() -> Providers:
        return providers_builder(load_settings(settings_path).output_format)

    @app.post("/api/runs", status_code=202)
    def start_run(body: RunRequest) -> JSONResponse:
        with manager.lock:
            if manager.active:
                return _error(409, "a run is already active")
            fmt = resolve_format(body.format, settings_path)
            providers = providers_builder(
                fmt,
                expand_playlist=body.playlist,
                limit=body.limit,
                on_event=manager.on_download_event,
            )
            try:
                manager.start(Source(url=body.url), providers, body.concurrency)
            except RunActiveError as active:  # pragma: no cover — guarded above
                return _error(409, str(active))
        return JSONResponse(status_code=202, content=manager.snapshot())

    @app.get("/api/runs/current")
    def current_run() -> dict:
        return manager.snapshot()

    @app.get("/api/runs/current/events")
    def run_events() -> StreamingResponse:
        def stream():
            snapshot, subscriber = manager.subscribe()
            yield _sse("snapshot", snapshot)
            if subscriber is None:
                # Already terminal (or idle): one state event, then close — the
                # same ending a live stream gets, so the client needs one path.
                yield _sse("state", {"state": snapshot["state"]})
                return
            try:
                while True:
                    try:
                        event = subscriber.get(timeout=15.0)
                    except queue_module.Empty:
                        # Comment line: keeps proxies from timing the stream out
                        # while a long download produces no events.
                        yield ": keep-alive\n\n"
                        continue
                    if event is None:  # close sentinel — after the state event
                        return
                    name, data = event
                    yield _sse(name, data)
            finally:
                manager.unsubscribe(subscriber)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/review")
    def review_list() -> dict:
        items = _review_providers().review_queue.items()
        return {
            "items": [
                wire.review_item_json(i, item, has_cover=_cover_bytes(item) is not None)
                for i, item in enumerate(items)
            ]
        }

    @app.post("/api/review/{index}/decision")
    def review_decision(index: int, body: DecisionRequest):
        # The whole pass runs under the manager's lock: the Review queue is
        # single-writer, so neither a run nor a second decision may interleave.
        with manager.lock:
            if manager.active:
                return _error(409, "a run is active — the Review queue has one writer")
            providers = _review_providers()
            items = providers.review_queue.items()
            if not (0 <= index < len(items)) or items[index].source_url != body.source_url:
                return _error(409, "stale review index: the queue changed under this listing")
            decision = ReviewDecision(
                action=body.action,
                tags=None
                if body.tags is None
                else Tags(
                    title=body.tags.title,
                    artist=body.tags.artist,
                    album=body.tags.album,
                    track_number=body.tags.track_number,
                    year=body.tags.year,
                ),
                hint=body.hint,
            )
            try:
                outcomes = clear_review_queue(
                    providers, _OneShotPrompter(index, body.source_url, decision)
                )
            except ValueError as invalid:
                # The engine's own guardrails (accept with no Tags, no file on
                # disk, an empty hint) — the queue file is untouched when they
                # fire, since the rewrite happens after the pass.
                return _error(400, str(invalid))
            outcome = outcomes[index]
        return {
            "cleared": outcome.cleared,
            "result": wire.track_result_json(outcome.result)
            if outcome.result is not None
            else None,
        }

    def _item_at(index: int) -> ReviewItem | None:
        items = _review_providers().review_queue.items()
        return items[index] if 0 <= index < len(items) else None

    @app.get("/api/review/{index}/audio")
    def review_audio(index: int):
        item = _item_at(index)
        # audio_path only, per the contract: output_path may name a file a later
        # decision will rewrite, but the audio to *listen* to is the download.
        if item is None or item.audio_path is None or not item.audio_path.exists():
            return _error(404, "no audio on disk for this entry")
        return FileResponse(item.audio_path, media_type=_audio_media_type(item.audio_path))

    @app.get("/api/review/{index}/cover")
    def review_cover(index: int):
        item = _item_at(index)
        cover = _cover_bytes(item) if item is not None else None
        if cover is None:
            return _error(404, "no cover art for this entry")
        return Response(content=cover, media_type="image/jpeg")

    @app.get("/api/settings")
    def get_settings() -> dict:
        return {"format": _FORMAT_NAMES[load_settings(settings_path).output_format]}

    @app.put("/api/settings")
    def put_settings(body: SettingsBody) -> dict:
        save_settings(Settings(output_format=FORMAT_CHOICES[body.format]), settings_path)
        return {"format": body.format}

    # Mounted last: everything the API didn't claim is the SPA's (index.html at /).
    spa_dir = static_dir if static_dir is not None else Path(__file__).parent / "static"
    if spa_dir.is_dir():
        app.mount("/", StaticFiles(directory=spa_dir, html=True), name="spa")

    #: Where the run's Tracks land — recorded for operators (the launch log names
    #: it); the routes themselves get every path from the providers.
    app.state.out_dir = out_dir
    return app
