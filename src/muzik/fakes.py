"""Fake providers — deterministic, no network, no disk. For the whole-box test.

Each mirrors the seam of its real counterpart so the engine can't tell them apart.
"""

from __future__ import annotations

from pathlib import Path

from muzik.domain import Match, Source, Tags, Track


class FakeDownloader:
    """Returns one canned Track for any Source (no network, no file written)."""

    def __init__(self, audio_path: Path = Path("/fake/audio.m4a"), title: str = "Fake Video"):
        self._audio_path = audio_path
        self._title = title

    def download(self, source: Source) -> list[Track]:
        return [Track(source_url=source.url, audio_path=self._audio_path, source_title=self._title)]


class FakeFingerprinter:
    """Returns a preset Match (or None to simulate no identification)."""

    def __init__(self, match: Match | None):
        self._match = match

    def identify(self, track: Track) -> Match | None:
        return self._match


class FakeAuthority:
    """Pass-through Tags, plus a canned MusicBrainz-by-ISRC album lookup.

    ``tags_for`` mirrors the skeleton (Tags from the Match's own identity).
    ``canonical_album`` stands in for the real Authority's ISRC lookup: it returns
    the preset ``studio_album`` (``None`` simulates a MusicBrainz miss) and records
    each ISRC it was asked about, so a whole-box test can assert whether — and with
    what — the Authority was consulted.
    """

    def __init__(self, studio_album: str | None = None) -> None:
        self._studio_album = studio_album
        self.canonical_album_calls: list[str | None] = []

    def tags_for(self, match: Match) -> Tags:
        return Tags(
            title=match.title,
            artist=match.artist,
            album=match.album,
            cover_art=match.cover_art,
        )

    def canonical_album(self, isrc: str | None) -> str | None:
        self.canonical_album_calls.append(isrc)
        return self._studio_album


class FakeResolver:
    """Injected for its seam; proposes nothing on the skeleton path."""

    def resolve(self, track: Track, match: Match | None) -> Match | None:
        return None


class FakeTagWriter:
    """Records what it was asked to write; returns a path without touching disk."""

    def __init__(self) -> None:
        self.written: list[tuple[Track, Tags]] = []

    def write(self, track: Track, tags: Tags) -> Path:
        self.written.append((track, tags))
        return track.audio_path
