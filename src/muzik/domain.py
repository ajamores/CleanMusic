"""Domain types for Muzik. Vocabulary follows CONTEXT.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ReviewAction = Literal["accept", "manual", "hint", "skip"]

#: The Resolver's ruling on whether a fingerprint identity fits a Track's own
#: evidence (ADR-0006). ``consistent`` — the evidence backs the Match; may verify.
#: ``inconsistent`` — the evidence contradicts it; route to Review. ``unsure`` —
#: not enough to tell (also the safe degradation when the AI call fails/timeouts,
#: ADR-0002): keep unverified, Review.
IdentityVerdict = Literal["consistent", "inconsistent", "unsure"]


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
    #: Runtime in whole seconds, as yt-dlp reports it, for the ``#EXTINF`` line of a
    #: ``--playlist`` run's ``.m3u8`` (#25). None when yt-dlp gives no duration.
    duration: int | None = None
    #: The Source's own description text, as yt-dlp extracts it. Captured as identity
    #: evidence for the Resolver's forthcoming identity ruling (#37, ADR-0006);
    #: nothing consumes it yet. "" when the entry carries none.
    description: str = ""
    #: The Source's tags/keywords from yt-dlp — further identity evidence for the
    #: Resolver (#37, ADR-0006). Empty list when the entry carries none. (Track is a
    #: reporting record, never hashed, so a list field is safe here.)
    tags: list[str] = field(default_factory=list)
    #: URL of the Source's thumbnail — the image the multimodal Resolver will read
    #: (#37, ADR-0006). Only the URL is captured here: it is cheap and always to hand
    #: in the info dict, so this ticket stays pure capture with no fetch; the bytes a
    #: multimodal call needs are pulled on demand where that call is assembled (#38).
    #: "" when the entry names no thumbnail.
    thumbnail_url: str = ""


@dataclass(frozen=True)
class Match:
    """A candidate identity for a Track, carrying a confidence."""

    title: str
    artist: str
    album: str
    cover_art: bytes | None = None
    isrc: str | None = None
    #: The MusicBrainz recording id, when the identifier supplies one directly
    #: (AcoustID does; Shazam does not, giving an ISRC instead — #51). The album
    #: waterfall resolves the canonical album from *either* handle, so an
    #: AcoustID-identified Track hydrates its album through MusicBrainz (#45) without
    #: the adapter making its own lookup. None when the identifier gives no id.
    recording_mbid: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class IdentityRuling:
    """The Resolver's identity verdict over a Track's full evidence (ADR-0006).

    Distinct from the Resolver's album-naming role: this rules on whether the
    *fingerprint's identity itself* is consistent with the Source's own metadata
    (title, channel, description, tags, thumbnail), so the Confidence gate can
    verify on an independent witness rather than on Shazam alone. The ``rationale``
    is a short human-readable line, carried for the Review output; the gate keys
    only off ``verdict``.
    """

    verdict: IdentityVerdict
    rationale: str = ""


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
class MatchConflict:
    """Why the Confidence gate kept a Track provisional (#24).

    What the fingerprint *heard*, set against the Source witnesses it failed to
    corroborate against — so the Review output can show the conflict, not just a
    terse reason. Carries only what that output renders: the rejected Match's
    identity and confidence, the Source's own witnesses (its title's artist half
    and the uploader/channel), and a short ``why`` naming which witness failed. A
    reporting record only — it never changes the gate's verify/provisional
    decision.
    """

    heard: Match
    #: The "Artist" half of the Source's own title, or "" when it names none.
    source_artist: str
    #: The channel as the gate weighed it — the normalised uploader ("… - Topic" /
    #: "VEVO" dressing stripped), or "" when it carries no artist. The gate's other
    #: artist witness.
    uploader: str
    #: A short line: which witness failed, and that the Track was kept provisional.
    why: str


@dataclass(frozen=True)
class TrackResult:
    """The engine's per-Track outcome: what was written, and where."""

    source_url: str
    tags: Tags | None
    output_path: Path | None
    #: "tagged" when a file was written, "review" when nothing was. An unidentified
    #: Track is now written best-effort from the Source (#52), so it is "tagged"
    #: with a ``reason`` set; only a Track with no usable Source identity (or a
    #: skip) stays "review".
    status: Literal["tagged", "review"]
    #: Why a Track is in the Review queue; None only for a verified, confirmed Track.
    #: A provisionally-written Track ("tagged" but unverified) still carries a reason.
    reason: str | None = None
    #: The rejected-Match conflict when the gate kept the Track provisional (#24);
    #: None for a verified Track or one that never got a Match to reject.
    conflict: MatchConflict | None = None


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
    #: The rejected-Match conflict, carried through so the ``--review`` clear pass
    #: renders the same explanation the batch did (#24). None when there is none.
    conflict: MatchConflict | None = None


@dataclass(frozen=True)
class PlaylistEntry:
    """One landed Track's line in a ``--playlist`` run's ``.m3u8`` (#25).

    Carries exactly what an extended-M3U entry needs: the runtime for ``#EXTINF``
    (None → ``-1``), the ``Artist``/``Title`` for its display half (from the Track's
    written Tags), and the file the entry points at. The writer turns ``path`` into a
    path relative to the playlist file's own folder, so moving the folder is safe.
    """

    duration: int | None
    artist: str
    title: str
    path: Path


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
