"""The five provider seams the engine depends on.

Each is a structural Protocol so a real and a fake implementation are
interchangeable. The engine holds all five; the skeleton flow only exercises
Downloader → Fingerprinter → Authority → TagWriter. Resolver is injected now so
its seam exists, and wired into the waterfall in a later ticket (ADR-0002).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from muzik.domain import Match, Source, Tags, Track


class Downloader(Protocol):
    """Turns a Source into one or more downloaded Tracks (a playlist yields many)."""

    def download(self, source: Source) -> list[Track]: ...


class Fingerprinter(Protocol):
    """Identifies a Track by acoustic fingerprint, or returns None (no match)."""

    def identify(self, track: Track) -> Match | None: ...


class Authority(Protocol):
    """Where a Track's canonical Tags and cover art come from once identified.

    The skeleton passes the Fingerprinter's own Match through; the waterfall
    (Shazam-own → MusicBrainz → Resolver) lands in a later ticket.
    """

    def tags_for(self, match: Match) -> Tags: ...


class Resolver(Protocol):
    """The AI step that reasons over a Track's evidence to propose an identity.

    Injected now for its seam; not called on the skeleton's happy path.
    """

    def resolve(self, track: Track, match: Match | None) -> Match | None: ...


class TagWriter(Protocol):
    """Writes Tags (and embedded cover art) into a Track's file; returns its path."""

    def write(self, track: Track, tags: Tags) -> Path: ...
