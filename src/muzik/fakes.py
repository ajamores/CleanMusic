"""Fake providers — deterministic, no network, no disk. For the whole-box test.

Each mirrors the seam of its real counterpart so the engine can't tell them apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from muzik.domain import Match, Source, Tags, Track
from muzik.settings import OutputFormat


class FakeDownloader:
    """Canned Tracks for any Source (no network, no file written).

    Extended for ticket #9: it honours an ``output_format`` (each Track's path
    takes that format's suffix) and simulates age-restricted entries. An
    age-restricted entry with no ``cookies`` is skipped — its reason is recorded
    on ``skipped`` and the rest of the batch still downloads, so nothing aborts.
    """

    def __init__(
        self,
        audio_path: Path = Path("/fake/audio.m4a"),
        title: str = "Fake Video",
        uploader: str = "",
        output_format: OutputFormat = OutputFormat.M4A,
        cookies: Path | None = None,
        entries: Sequence[tuple[str, bool]] | None = None,
    ):
        self._audio_path = audio_path
        self._title = title
        self._uploader = uploader
        self._output_format = output_format
        self._cookies = cookies
        #: Each entry is ``(title, age_restricted)``.
        self._entries = list(entries) if entries is not None else [(title, False)]
        #: ``(title, reason)`` for every entry skipped this batch.
        self.skipped: list[tuple[str, str]] = []

    def download(self, source: Source) -> list[Track]:
        tracks: list[Track] = []
        for index, (title, age_restricted) in enumerate(self._entries):
            if age_restricted and self._cookies is None:
                self.skipped.append(
                    (title, "age-restricted Source needs --cookies to download")
                )
                continue
            base = self._audio_path if index == 0 else Path(f"/fake/audio-{index}")
            tracks.append(
                Track(
                    source_url=source.url,
                    audio_path=base.with_suffix(self._output_format.file_suffix),
                    source_title=title,
                    uploader=self._uploader,
                )
            )
        return tracks


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
    """Records what it was asked to write; returns a path without touching disk.

    Extended for ticket #9: the returned path takes the configured
    ``output_format``'s suffix, so a whole-box test can see the saved setting
    reach the write step.
    """

    def __init__(self, output_format: OutputFormat = OutputFormat.M4A) -> None:
        self.written: list[tuple[Track, Tags]] = []
        self._output_format = output_format

    def write(self, track: Track, tags: Tags) -> Path:
        self.written.append((track, tags))
        return track.audio_path.with_suffix(self._output_format.file_suffix)
