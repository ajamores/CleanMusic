"""Domain types for Muzik. Vocabulary follows CONTEXT.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ReviewAction = Literal["accept", "manual", "hint", "skip"]


@dataclass(frozen=True)
class Source:
    """A YouTube URL the user submits — a single video or a playlist."""

    url: str


@dataclass(frozen=True)
class Track:
    """One downloaded audio file — the unit of output, and the thing tagged."""

    source_url: str
    audio_path: Path
    #: The Source's own title (channel/video title), used later by the Confidence gate.
    source_title: str = ""
    #: The Source's uploader/channel — the gate's artist witness and the
    #: provisional fallback artist when the title carries no "Artist -" (#11).
    uploader: str = ""


@dataclass(frozen=True)
class Match:
    """A candidate identity for a Track, carrying a confidence."""

    title: str
    artist: str
    album: str
    cover_art: bytes | None = None
    isrc: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class Tags:
    """Metadata written into a Track's file. Either verified or provisional."""

    title: str
    artist: str
    album: str
    cover_art: bytes | None = None
    track_number: int | None = None
    year: int | None = None
    #: True once a Match has passed the Confidence gate. Skeleton writes provisional.
    verified: bool = False


@dataclass(frozen=True)
class TrackResult:
    """The engine's per-Track outcome: what was written, and where."""

    source_url: str
    tags: Tags | None
    output_path: Path | None
    #: "tagged" when a file was written, "review" when nothing was (no Match / skip).
    status: Literal["tagged", "review"]
    #: Why a Track is in the Review queue; None only for a verified, confirmed Track.
    #: A provisionally-written Track ("tagged" but unverified) still carries a reason.
    reason: str | None = None


@dataclass(frozen=True)
class ReviewItem:
    """One entry in the persisted Review queue: a Track the user must clear.

    Carries whatever the batch could establish — provisional ``tags`` (None when
    the Track was never identified or never downloaded), where the file landed if
    one was written, and the ``reason`` it needs review.

    ``audio_path`` is where the downloaded audio lives on disk — known whenever a
    Track was downloaded, even for a fingerprint miss that wrote no Tags. The
    clear pass (#7) needs it to write accepted/manual Tags and to re-fingerprint
    on a hint; it is None only for an entry that never became a Track (a skipped
    download).
    """

    source_url: str
    reason: str
    tags: Tags | None = None
    output_path: Path | None = None
    audio_path: Path | None = None


@dataclass(frozen=True)
class ReviewDecision:
    """What the user chose to do with one Review-queue entry (#7).

    ``accept`` verifies the entry's own provisional ``tags``; ``manual`` writes
    the user-supplied ``tags``; ``hint`` re-runs Identification with ``hint`` as a
    corrected "Artist - Title"; ``skip`` leaves the entry in the queue.
    """

    action: ReviewAction
    tags: Tags | None = None
    hint: str | None = None
