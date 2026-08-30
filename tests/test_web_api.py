"""Offline tests for the web adapter (API CONTRACT v1), over fake providers.

Every seam is a fake from src/muzik/fakes.py — no network, no real downloads.
Timing is controlled with a gate the test opens (a Downloader that blocks until
released), never with sleeps: SSE ordering and the active-run 409s need a run
that is *provably* still in flight when the assertion fires.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from muzik.domain import Match, MatchConflict, ReviewItem, Source, Tags
from muzik.engine import Providers
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeReviewQueue,
    FakeTagWriter,
)
from muzik.providers import PlaylistInSingleModeError
from muzik.real.review_queue import JsonReviewQueue
from muzik.settings import OutputFormat
from muzik.web.app import create_app
from muzik.web.jobs import RunManager

#: A Source title + Match pair the Confidence gate verifies outright (title and
#: artist both corroborated), so a run produces a verified Track with no witness.
VERIFIED_TITLE = "Rick Astley - Never Gonna Give You Up"
VERIFIED_MATCH = Match(
    title="Never Gonna Give You Up",
    artist="Rick Astley",
    album="Whenever You Need Somebody",
    confidence=1.0,
)


class GatedDownloader(FakeDownloader):
    """A FakeDownloader that blocks until the test releases it, so a run is
    verifiably active while the test asserts against it."""

    def __init__(self, gate: threading.Event, **kwargs) -> None:
        super().__init__(**kwargs)
        self._gate = gate

    def download(self, source: Source):
        assert self._gate.wait(timeout=10), "test gate never released"
        return super().download(source)


class RefusingDownloader(FakeDownloader):
    """Simulates the bare-playlist-in-single-mode refusal (ADR-0004)."""

    def download(self, source: Source):
        raise PlaylistInSingleModeError("bare playlist Source in single mode; pass playlist")


def make_providers(downloader, review_queue=None, match=VERIFIED_MATCH) -> Providers:
    return Providers(
        downloader=downloader,
        fingerprinter=FakeFingerprinter(match),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=FakeTagWriter(),
        review_queue=review_queue if review_queue is not None else FakeReviewQueue(),
    )


def make_client(providers: Providers, tmp_path: Path) -> TestClient:
    def builder(fmt: OutputFormat, *, expand_playlist=False, limit=None, on_event=None):
        return providers

    app = create_app(builder, tmp_path, settings_path=tmp_path / "settings.json")
    return TestClient(app)


def sse_events(lines) -> list[tuple[str, dict]]:
    """Parse a whole SSE stream into (event, payload) pairs, skipping keep-alives.

    TestClient buffers a streaming response until the app closes it, so this
    reads the complete stream — which the contract guarantees ends after a
    terminal state event.
    """
    events: list[tuple[str, dict]] = []
    name = None
    for line in lines:
        if line.startswith(":") or not line.strip():
            continue
        if line.startswith("event: "):
            name = line[len("event: "):]
        elif line.startswith("data: "):
            assert name is not None, f"data with no event name: {line!r}"
            events.append((name, json.loads(line[len("data: "):])))
            name = None
    return events


def release_on_subscribe(manager, gate: threading.Event) -> None:
    """Open the test gate once the SSE subscriber is registered.

    TestClient's transport runs the app to completion before handing back the
    body, so the gate can't be opened between reads; releasing it at the moment
    of subscription still proves the snapshot precedes every track event — the
    subscriber was registered (snapshot taken, under the manager's lock) while
    the run was verifiably still gated.
    """

    def wait_then_release():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with manager.lock:
                if manager._subscribers:
                    break
            time.sleep(0.01)
        gate.set()

    threading.Thread(target=wait_then_release, daemon=True).start()


# --- Run lifecycle ---------------------------------------------------------------


def test_run_lifecycle_and_sse_event_order(tmp_path):
    gate = threading.Event()
    downloader = GatedDownloader(
        gate,
        audio_path=tmp_path / "audio.m4a",
        uploader="RickAstleyVEVO",
        entries=[(VERIFIED_TITLE, False), ("Somebody Else - A Different Song", False)],
    )
    client = make_client(make_providers(downloader), tmp_path)

    response = client.post("/api/runs", json={"url": "https://youtu.be/x"})
    assert response.status_code == 202
    assert response.json()["state"] == "running"
    assert response.json()["url"] == "https://youtu.be/x"

    release_on_subscribe(client.app.state.manager, gate)
    with client.stream("GET", "/api/runs/current/events") as stream:
        events = sse_events(stream.iter_lines())

    # Snapshot first — taken while the run was still gated, so it shows the run
    # in flight with no results — then one track event per Track in drain order,
    # then the terminal state, after which the stream closed (iteration ended).
    assert [name for name, _ in events] == ["snapshot", "track", "track", "state"]
    snapshot = events[0][1]
    assert snapshot["state"] == "running" and snapshot["results"] == []
    assert events[1][1]["status"] == "tagged" and events[1][1]["reason"] is None
    assert events[2][1]["conflict"] is not None
    assert events[3][1] == {"state": "done"}

    client.app.state.manager.wait(5)
    state = client.get("/api/runs/current").json()
    assert state["state"] == "done"
    assert len(state["results"]) == 2
    verified, queued = state["results"]
    assert verified["reason"] is None and verified["tags"]["verified"] is True
    assert queued["reason"] is not None and queued["conflict"] is not None
    assert state["summary"] == {"verified": 1, "queued": 1}
    assert state["error"] is None


def test_second_run_refused_while_active(tmp_path):
    gate = threading.Event()
    providers = make_providers(GatedDownloader(gate, audio_path=tmp_path / "a.m4a"))
    client = make_client(providers, tmp_path)
    assert client.post("/api/runs", json={"url": "u1"}).status_code == 202

    second = client.post("/api/runs", json={"url": "u2"})
    assert second.status_code == 409
    assert "error" in second.json()

    gate.set()
    client.app.state.manager.wait(5)
    assert client.get("/api/runs/current").json()["state"] == "done"


def test_playlist_refusal_becomes_refused_state_not_500(tmp_path):
    client = make_client(make_providers(RefusingDownloader()), tmp_path)
    response = client.post("/api/runs", json={"url": "https://youtube.com/playlist?list=PL1"})
    assert response.status_code == 202
    client.app.state.manager.wait(5)

    state = client.get("/api/runs/current").json()
    assert state["state"] == "refused"
    assert "bare playlist" in state["error"]
    assert state["summary"] is None

    # A stream opened after the terminal state: snapshot, one state event, close.
    with client.stream("GET", "/api/runs/current/events") as stream:
        events = sse_events(stream.iter_lines())
    assert [n for n, _ in events] == ["snapshot", "state"]
    assert events[1][1] == {"state": "refused"}


def test_idle_state_shape(tmp_path):
    client = make_client(make_providers(FakeDownloader()), tmp_path)
    state = client.get("/api/runs/current").json()
    assert state == {
        "state": "idle",
        "url": None,
        "results": [],
        "skipped": [],
        "archive_skips": [],
        "playlist_path": None,
        "summary": None,
        "error": None,
    }


def test_skipped_downloads_reported(tmp_path):
    downloader = FakeDownloader(
        audio_path=tmp_path / "a.m4a",
        entries=[(VERIFIED_TITLE, False), ("Age Restricted One", True)],
    )
    client = make_client(make_providers(downloader), tmp_path)
    client.post("/api/runs", json={"url": "u"})
    client.app.state.manager.wait(5)
    state = client.get("/api/runs/current").json()
    assert state["skipped"] == [
        {
            "source_url": "Age Restricted One",
            "reason": "age-restricted Source needs --cookies to download",
        }
    ]
    # The skip counts as queued in the summary, as in the CLI (engine.summarize).
    assert state["summary"] == {"verified": 1, "queued": 1}


def test_download_event_forwards_title_and_raw_speed():
    # The Downloader emits ``title`` precisely because its outtmpl makes
    # ``filename`` an opaque %(id)s path (downloader.py, _emit_event); the
    # manager must pass it through — and only the contract's four fields.
    manager = RunManager()
    manager.state = "running"
    _, subscriber = manager.subscribe()
    manager.on_download_event(
        {
            "filename": "downloads/dQw4w9WgXcQ.webm.part",
            "percent": 42.0,
            "speed": 2381423.55,
            "title": "Never Gonna Give You Up",
            "downloaded_bytes": 12345,  # adapter-internal extra: must not leak
        }
    )
    name, data = subscriber.get_nowait()
    assert name == "download"
    assert data == {
        "filename": "downloads/dQw4w9WgXcQ.webm.part",
        "percent": 42.0,
        "speed": 2381423.55,
        "title": "Never Gonna Give You Up",
    }


# --- Review queue ----------------------------------------------------------------


def seeded_queue(tmp_path) -> FakeReviewQueue:
    audio = tmp_path / "kept.m4a"
    audio.write_bytes(b"fake audio bytes")
    return FakeReviewQueue(
        [
            ReviewItem(
                source_url="https://youtu.be/one",
                reason="unverified: provisional Tags from the Source, Match not corroborated",
                tags=Tags(title="Kept Song", artist="Kept Artist", album="", verified=False),
                output_path=audio,
                audio_path=audio,
                conflict=MatchConflict(
                    heard=Match(title="Heard", artist="Someone", album="Album", confidence=1.0),
                    source_artist="Kept Artist",
                    uploader="Chan",
                    why="title didn't match, kept provisional",
                    witness_rationale="the channel names a different artist",
                ),
            ),
            ReviewItem(
                source_url="https://youtu.be/two",
                reason="age-restricted Source needs --cookies to download",
            ),
            ReviewItem(
                source_url="https://youtu.be/three",
                reason="no fingerprint match",
                tags=Tags(
                    title="Covered", artist="Someone", album="", cover_art=b"jpegbytes",
                    verified=False,
                ),
                output_path=tmp_path / "kept.m4a",
                audio_path=audio,
            ),
        ]
    )


def test_review_listing_shape(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    items = client.get("/api/review").json()["items"]
    assert [item["index"] for item in items] == [0, 1, 2]
    first = items[0]
    assert first["source_url"] == "https://youtu.be/one"
    assert first["tags"]["title"] == "Kept Song"
    assert first["conflict"]["heard"]["album"] == "Album"
    assert first["conflict"]["witness_rationale"] == "the channel names a different artist"
    assert first["has_audio"] is True and first["has_cover"] is False
    assert items[1]["tags"] is None and items[1]["has_audio"] is False
    assert items[2]["has_cover"] is True
    # cover_art bytes never appear inline in JSON — only via the cover endpoint.
    assert "jpegbytes" not in client.get("/api/review").text


def test_accept_clears_entry_and_skips_survive(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    response = client.post(
        "/api/review/0/decision",
        json={"action": "accept", "source_url": "https://youtu.be/one"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cleared"] is True
    assert body["result"]["tags"]["verified"] is True
    assert body["result"]["tags"]["title"] == "Kept Song"
    # The engine's survivor semantics: every other entry kept, in order.
    remaining = client.get("/api/review").json()["items"]
    assert [item["source_url"] for item in remaining] == [
        "https://youtu.be/two",
        "https://youtu.be/three",
    ]


def test_skip_leaves_entry_queued(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    body = client.post(
        "/api/review/0/decision",
        json={"action": "skip", "source_url": "https://youtu.be/one"},
    ).json()
    assert body == {"cleared": False, "result": None}
    assert len(client.get("/api/review").json()["items"]) == 3


def test_manual_decision_writes_supplied_tags(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    body = client.post(
        "/api/review/0/decision",
        json={
            "action": "manual",
            "source_url": "https://youtu.be/one",
            "tags": {"title": "Right Title", "artist": "Right Artist", "album": "Right Album"},
        },
    ).json()
    assert body["cleared"] is True
    assert body["result"]["tags"] == {
        "title": "Right Title",
        "artist": "Right Artist",
        "album": "Right Album",
        "track_number": None,
        "year": None,
        "verified": True,
    }


def test_stale_source_url_is_409(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    response = client.post(
        "/api/review/0/decision",
        json={"action": "accept", "source_url": "https://youtu.be/some-other"},
    )
    assert response.status_code == 409
    assert "stale" in response.json()["error"]
    assert len(client.get("/api/review").json()["items"]) == 3


def test_out_of_range_index_is_409(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    response = client.post(
        "/api/review/9/decision",
        json={"action": "accept", "source_url": "https://youtu.be/one"},
    )
    assert response.status_code == 409


def test_decision_refused_while_run_active(tmp_path):
    gate = threading.Event()
    queue = seeded_queue(tmp_path)
    providers = make_providers(
        GatedDownloader(gate, audio_path=tmp_path / "a.m4a"), review_queue=queue
    )
    client = make_client(providers, tmp_path)
    client.post("/api/runs", json={"url": "u"})
    response = client.post(
        "/api/review/0/decision",
        json={"action": "accept", "source_url": "https://youtu.be/one"},
    )
    assert response.status_code == 409
    gate.set()
    client.app.state.manager.wait(5)


def test_invalid_decision_is_400_and_queue_untouched(tmp_path):
    # Accepting the skipped-download entry: no provisional Tags — the engine's
    # own ValueError, surfaced as a 400 with the queue file unrewritten.
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    response = client.post(
        "/api/review/1/decision",
        json={"action": "accept", "source_url": "https://youtu.be/two"},
    )
    assert response.status_code == 400
    assert len(client.get("/api/review").json()["items"]) == 3


# --- Review media ----------------------------------------------------------------


def test_review_audio_served_with_content_type(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    response = client.get("/api/review/0/audio")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mp4")
    assert response.content == b"fake audio bytes"


def test_review_audio_404_when_no_audio_path(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    assert client.get("/api/review/1/audio").status_code == 404
    assert client.get("/api/review/99/audio").status_code == 404


def test_review_cover_bytes_and_404(tmp_path):
    queue = seeded_queue(tmp_path)
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    response = client.get("/api/review/2/cover")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"jpegbytes"
    assert client.get("/api/review/0/cover").status_code == 404
    assert client.get("/api/review/1/cover").status_code == 404
    assert client.get("/api/review/99/cover").status_code == 404


def test_cover_recovered_from_written_file_after_real_queue_roundtrip(tmp_path):
    # The real queue drops cover_art on persist (review_queue.py) — the
    # provisionally-written file holds it. has_cover and the cover endpoint
    # must read it back from the file, or real listings can never show art.
    from mutagen.id3 import APIC, ID3

    audio = tmp_path / "kept.mp3"
    audio.write_bytes(b"\x00" * 32)  # ID3 needs only a file to prepend a tag to
    id3 = ID3()
    id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="cover", data=b"embedded-art"))
    id3.save(audio)

    queue = JsonReviewQueue(tmp_path / "review-queue.jsonl")
    queue.enqueue(
        ReviewItem(
            source_url="https://youtu.be/real",
            reason="no fingerprint match",
            tags=Tags(title="T", artist="A", album="", verified=False),
            output_path=audio,
            audio_path=audio,
        )
    )
    client = make_client(make_providers(FakeDownloader(), review_queue=queue), tmp_path)
    items = client.get("/api/review").json()["items"]
    assert items[0]["has_cover"] is True
    response = client.get("/api/review/0/cover")
    assert response.status_code == 200
    assert response.content == b"embedded-art"


# --- Settings --------------------------------------------------------------------


def test_settings_roundtrip(tmp_path):
    client = make_client(make_providers(FakeDownloader()), tmp_path)
    assert client.get("/api/settings").json() == {"format": "m4a"}
    assert client.put("/api/settings", json={"format": "mp3-320"}).json() == {
        "format": "mp3-320"
    }
    assert client.get("/api/settings").json() == {"format": "mp3-320"}


def test_settings_rejects_unknown_format(tmp_path):
    client = make_client(make_providers(FakeDownloader()), tmp_path)
    assert client.put("/api/settings", json={"format": "flac"}).status_code == 422


def test_run_format_choice_is_persisted(tmp_path):
    # The run body's explicit format follows the CLI's --format rule: saved as
    # the new default (wiring.resolve_format's contract).
    client = make_client(make_providers(FakeDownloader()), tmp_path)
    client.post("/api/runs", json={"url": "u", "format": "mp3-320"})
    client.app.state.manager.wait(5)
    assert client.get("/api/settings").json() == {"format": "mp3-320"}


# --- Demo mode -------------------------------------------------------------------


def test_demo_refuses_bare_playlist_in_single_mode(tmp_path):
    # The demo mirrors the real Downloader's ADR-0004 refusal, so the SPA's
    # "refused" state is drivable against the demo backend, not only in tests.
    from muzik.web.demo import build_demo

    app = create_app(build_demo(tmp_path / "demo"), tmp_path, settings_path=tmp_path / "s.json")
    client = TestClient(app)
    response = client.post(
        "/api/runs", json={"url": "https://www.youtube.com/playlist?list=PL1"}
    )
    assert response.status_code == 202
    app.state.manager.wait(5)
    state = client.get("/api/runs/current").json()
    assert state["state"] == "refused"
    assert "playlist" in state["error"]
