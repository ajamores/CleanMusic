"""--demo mode: fake providers seeded so the UI has something to render.

Everything is offline and instant (src/muzik/fakes.py stands in for every
network seam), and the Review queue is pre-seeded with one entry per rendering
path the SPA has — a Match conflict with a witness rationale, a fingerprint miss
with provisional Tags, a skipped download, and an entry carrying cover art.
Demo state lives in its own directory (settings included, via the app factory's
``settings_path``) so a demo never touches the user's library or settings.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path

from muzik.domain import Match, MatchConflict, ReviewItem, Tags, Track
from muzik.engine import Providers
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeResolver,
    FakeReviewQueue,
    FakeTagWriter,
)
from muzik.providers import PlaylistInSingleModeError
from muzik.settings import OutputFormat

#: A valid 1×1 JPEG, embedded so the cover endpoint serves real image bytes with
#: no asset file and no network. Browsers render it (scaled up, plainly a demo).
_TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)

#: The demo batch: two Sources the fingerprinter identifies (their titles
#: corroborate the Match, so they verify with no witness call) and one it
#: misses (best-effort provisional Tags, routed to Review).
_ENTRIES = [
    ("Rick Astley - Never Gonna Give You Up", False),
    ("Daft Punk - One More Time", False),
    ("late night drive (unreleased mix)", False),
]

_MATCHES = {
    "Rick Astley - Never Gonna Give You Up": Match(
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        album="Whenever You Need Somebody",
        confidence=1.0,
    ),
    "Daft Punk - One More Time": Match(
        title="One More Time", artist="Daft Punk", album="Discovery", confidence=1.0
    ),
}


class _RefusingDownloader(FakeDownloader):
    """FakeDownloader plus the real Downloader's bare-playlist refusal (ADR-0004),
    so the demo can drive the contract's "refused" state end to end. The real
    check is yt-dlp's classification; a URL sniff is close enough for a demo."""

    def download(self, source):
        if "list=" in source.url and "v=" not in source.url:
            raise PlaylistInSingleModeError(
                "that's a playlist; pass --playlist to download all of it"
            )
        return super().download(source)


class _CannedFingerprinter:
    """Per-title Matches, so one demo batch shows both verified and queued Tracks
    (FakeFingerprinter answers uniformly, which can't)."""

    def identify(self, track: Track) -> Match | None:
        return _MATCHES.get(track.source_title)


def _placeholder_audio(demo_dir: Path, name: str) -> Path:
    # Not decodable audio — just bytes on disk so the review audio endpoint has
    # a file to serve and the SPA a player to show. The player failing to play
    # a demo placeholder is accepted; generating real AAC would need ffmpeg.
    path = demo_dir / name
    path.write_bytes(b"muzik demo placeholder \x00" * 64)
    return path


def _seed_items(demo_dir: Path) -> list[ReviewItem]:
    conflict_audio = _placeholder_audio(demo_dir, "have-you-seen-her.m4a")
    miss_audio = _placeholder_audio(demo_dir, "city-pop-mix.m4a")
    cover_audio = _placeholder_audio(demo_dir, "midnight-city.m4a")
    return [
        # 1. A Match conflict, witness rationale included — the docs/LEARNINGS.md
        # anchoring case, so the demo shows a realistic false rejection.
        ReviewItem(
            source_url="https://www.youtube.com/watch?v=demo-conflict",
            reason="unverified: provisional Tags from the Source, Match not corroborated",
            tags=Tags(title="Have You Seen Her", artist="Dru Hill", album="", verified=False),
            output_path=conflict_audio,
            audio_path=conflict_audio,
            conflict=MatchConflict(
                heard=Match(
                    title="Have You Seen Her",
                    artist="Dru Hill",
                    album="Where I Wanna Be",
                    confidence=1.0,
                ),
                source_artist="",
                uploader="Dru Hill",
                why="the identity witness ruled the Match inconsistent with the video, kept provisional",
                witness_rationale=(
                    "The thumbnail names 'Where I Wanna Be', which contradicts the "
                    "claimed title 'Have You Seen Her'."
                ),
            ),
        ),
        # 2. A fingerprint miss: provisional Tags from the Source, no conflict.
        ReviewItem(
            source_url="https://www.youtube.com/watch?v=demo-miss",
            reason="no fingerprint match",
            tags=Tags(title="City Pop Mix Vol. 3", artist="DJ Yotsuba", album="", verified=False),
            output_path=miss_audio,
            audio_path=miss_audio,
        ),
        # 3. A skipped download: never became a Track — no Tags, no file.
        ReviewItem(
            source_url="https://www.youtube.com/watch?v=demo-skip",
            reason="age-restricted Source needs --cookies to download",
        ),
        # 4. Cover art present, so the cover endpoint and thumbnail render show.
        ReviewItem(
            source_url="https://www.youtube.com/watch?v=demo-cover",
            reason="unverified: no independent witness to confirm the Match",
            tags=Tags(
                title="Midnight City",
                artist="M83",
                album="Hurry Up, We're Dreaming",
                cover_art=_TINY_JPEG,
                verified=False,
            ),
            output_path=cover_audio,
            audio_path=cover_audio,
        ),
    ]


def build_demo(demo_dir: Path) -> Callable[..., Providers]:
    """The demo ProvidersBuilder. The Review queue is one in-memory instance
    shared across builds — the persistence a real run gets from the queue file —
    so listing, deciding, and re-listing behave like the real thing."""
    demo_dir.mkdir(parents=True, exist_ok=True)
    review_queue = FakeReviewQueue(_seed_items(demo_dir))

    def build(
        fmt: OutputFormat,
        *,
        expand_playlist: bool = False,
        limit: int | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> Providers:
        downloader_cls = FakeDownloader if expand_playlist else _RefusingDownloader
        downloader = downloader_cls(
            audio_path=demo_dir / "demo-track.m4a",
            uploader="Demo Channel",
            output_format=fmt,
            entries=_ENTRIES if expand_playlist else _ENTRIES[:1],
        )
        if expand_playlist:
            downloader.playlist_title = "muzik demo playlist"
        return Providers(
            downloader=downloader,
            fingerprinter=_CannedFingerprinter(),
            authority=FakeAuthority(),
            resolver=FakeResolver(),
            tagwriter=FakeTagWriter(output_format=fmt),
            review_queue=review_queue,
        )

    return build
