"""The five provider seams the engine depends on.

Each is a structural Protocol so a real and a fake implementation are
interchangeable. The engine holds all five; the skeleton flow only exercises
Downloader → Fingerprinter → Authority → TagWriter. Resolver is injected now so
its seam exists, and wired into the waterfall in a later ticket (ADR-0002).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from muzik.domain import Match, ReviewDecision, ReviewItem, Source, Tags, Track


class Downloader(Protocol):
    """Turns a Source into one or more downloaded Tracks (a playlist yields many)."""

    #: ``(title_or_url, reason)`` for every entry skipped this batch (e.g. an
    #: age-restricted Source without cookies). A skip routes to the Review queue
    #: rather than aborting the batch (ADR-0002); the engine drains this after
    #: download.
    skipped: list[tuple[str, str]]

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

    def canonical_album(self, isrc: str | None) -> str | None:
        """The recording's canonical studio album by ISRC, or None on a miss."""
        ...


class Resolver(Protocol):
    """The AI step that reasons over a Track's evidence to propose an identity.

    Injected now for its seam; not called on the skeleton's happy path.
    """

    def resolve(self, track: Track, match: Match | None) -> Match | None: ...


class TagWriter(Protocol):
    """Writes Tags (and embedded cover art) into a Track's file; returns its path."""

    def write(self, track: Track, tags: Tags) -> Path: ...


class ReviewQueue(Protocol):
    """The persisted set of Tracks too uncertain to auto-tag (CONTEXT.md).

    The engine appends to it during a batch; the batch never blocks on it. The
    read/clear side (#7) reads every entry back with ``items`` and rewrites the
    survivors with ``replace_all`` once the user has worked through them.
    """

    def enqueue(self, item: ReviewItem) -> None: ...

    def items(self) -> list[ReviewItem]:
        """Every entry currently in the queue, in the order it was enqueued."""
        ...

    def replace_all(self, items: list[ReviewItem]) -> None:
        """Overwrite the queue with ``items`` — the survivors of a clear pass."""
        ...


class ReviewPrompter(Protocol):
    """Asks the user what to do with one Review-queue entry (#7).

    The clear side of the engine is interface-agnostic (ADR-0001): it drives this
    seam rather than reading input itself. The CLI implements it over stdin; a
    test scripts it.
    """

    def decide(self, item: ReviewItem) -> ReviewDecision: ...
