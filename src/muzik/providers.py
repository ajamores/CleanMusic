"""The five provider seams the engine depends on.

Each is a structural Protocol so a real and a fake implementation are
interchangeable. The engine holds all five; the skeleton flow only exercises
Downloader → Fingerprinter → Authority → TagWriter. Resolver is injected now so
its seam exists, and wired into the waterfall in a later ticket (ADR-0002).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from muzik.domain import (
    IdentityRuling,
    Match,
    PlaylistEntry,
    ReviewDecision,
    ReviewItem,
    Source,
    Tags,
    Track,
)


class PlaylistInSingleModeError(Exception):
    """A bare-playlist Source was submitted in single mode (ADR-0004).

    Single mode identifies one Track; ``noplaylist`` collapses a
    ``watch?v=…&list=…`` link to its video, but a *bare* playlist URL has no video
    to fall back to and would expand fully. Rather than silently pick one track or
    expand, the Downloader refuses such a Source *before* downloading anything and
    raises this — a whole-Source rejection, distinct from a per-Track skip (which
    routes to Review and lets the batch continue). The adapter surfaces the
    message and hands the choice back to the user (pass ``--playlist``).
    """


class Downloader(Protocol):
    """Turns a Source into one or more downloaded Tracks (a playlist yields many)."""

    #: ``(title_or_url, reason)`` for every entry skipped this batch (e.g. an
    #: age-restricted Source without cookies). A skip routes to the Review queue
    #: rather than aborting the batch (ADR-0002); the engine drains this after
    #: download.
    skipped: list[tuple[str, str]]

    #: The expanded playlist's own title, as yt-dlp classifies it (#25) — set only
    #: when a ``--playlist`` run expanded a Source into a playlist, ``None`` in
    #: single mode. The engine reads it after ``download`` to name the ``.m3u8`` it
    #: writes for the run, never from Muzik-side URL parsing.
    playlist_title: str | None

    def download(self, source: Source) -> list[Track]:
        """Download the Source's Tracks.

        Raises ``PlaylistInSingleModeError`` when a bare playlist URL is submitted
        in single mode — the whole Source is refused before anything downloads.
        """
        ...

    def record_processed(self, track: Track) -> None:
        """Mark a downloaded Track done, so a later run skips it (#65).

        The engine calls this once the Track's outcome is on disk — never at
        download, or an interrupted batch would leave untagged Tracks that no
        re-run revisits. Must not raise: bookkeeping never aborts a batch (#32).
        """
        ...


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

    def canonical_album_for_recording(self, recording_mbid: str | None) -> str | None:
        """The canonical studio album for a MusicBrainz recording id, or None.

        The by-recording twin of ``canonical_album``, for an identifier that hands
        back a recording id directly (AcoustID, #51) rather than an ISRC — it skips
        the ISRC→recording resolution and browses the recording's releases straight
        away. Same studio-album filter, same never-crash contract.
        """
        ...


class Resolver(Protocol):
    """The AI step that reasons over a Track's evidence (ADR-0006).

    Two distinct capabilities: ``resolve`` proposes a canonical *album* (the last
    tier of the album waterfall, ADR-0002), and ``witness_identity`` rules on
    whether the *fingerprint's identity* fits the Track's own evidence, so the
    Confidence gate can verify on an independent witness rather than Shazam alone.
    """

    def resolve(self, track: Track, match: Match | None) -> Match | None: ...

    def witness_identity(
        self, track: Track, match: Match, second: Match | None = None
    ) -> IdentityRuling:
        """Rule on whether ``match`` is consistent with the Track's own evidence.

        Reasons over the fingerprint Match *and* the full download — title,
        channel, description, tags, and thumbnail (a multimodal call) — and returns
        an :class:`IdentityRuling`. Must degrade to an ``unsure`` verdict on any
        failure or timeout rather than raise: a batch never blocks (ADR-0002).

        ``second`` is an optional *second, independent acoustic identification* of
        the same Track — a different fingerprinter's Match (AcoustID, #51, ADR-0006).
        When present it is weighed as evidence about what the audio actually is:
        two acoustic sources agreeing is stronger than the video's own title/channel
        (which an impersonator can type), and their disagreement is itself a signal.
        ``None`` when no second source ran (the Shazam-only case).

        The gate consults the witness only when the Source title echoes ``match``'s
        song and ``second`` does not name the same recording — three agreeing claims
        verify without it (#93) — so an implementation may take the title's song
        agreement as given.
        """
        ...


class TagWriter(Protocol):
    """Writes Tags (and embedded cover art) into a Track's file; returns its path."""

    def write(self, track: Track, tags: Tags) -> Path: ...


class ThumbnailFetcher(Protocol):
    """Fetches a Track's thumbnail as raw image bytes, for the artwork fallback (#52).

    The last-resort cover art: when identification leaves a Track with no real
    ``cover_art``, its video thumbnail is embedded so no file ships bare. Returns
    the raw bytes (the tag writer sniffs PNG vs JPEG itself), or ``None`` on a
    missing URL, a timeout, or any fetch error — the Track then degrades to bare
    rather than blocking the batch (ADR-0002), the same contract as the other
    network tiers.
    """

    def fetch(self, url: str) -> bytes | None: ...


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


class PlaylistWriter(Protocol):
    """Writes one ``.m3u8`` preserving a ``--playlist`` run's grouping (#25).

    A ``--playlist`` run's Tracks each carry their real album in their Tags; the
    *grouping* (the monthly YouTube playlist they came from) has nowhere to live in
    the files. This seam records it beside them as a plain playlist file a music
    library imports, leaving the album Tags untouched. Interface-specific output —
    a future web adapter would present the grouping differently — so it is a seam
    the engine drives, not core pipeline logic.
    """

    #: The file the most recent ``write`` produced (``None`` if it wrote none). The
    #: engine drives ``write`` but discards its return; the adapter reads the path
    #: back here afterwards — the same post-call-state pattern as the Downloader's
    #: ``skipped`` / ``archive_skips``.
    last_written: Path | None

    def write(self, title: str, entries: list[PlaylistEntry]) -> Path | None:
        """Write the playlist named ``title`` listing ``entries``, in order.

        Returns the file written, or ``None`` when there was nothing to write; the
        same path is recorded on ``last_written`` for a driver that discards it.
        """
        ...


class ReviewPrompter(Protocol):
    """Asks the user what to do with one Review-queue entry (#7).

    The clear side of the engine is interface-agnostic (ADR-0001): it drives this
    seam rather than reading input itself. The CLI implements it over stdin; a
    test scripts it.
    """

    def decide(self, item: ReviewItem) -> ReviewDecision: ...
