"""The core engine: the single entry point over the five provider seams.

Interface-agnostic (ADR-0001) — it knows nothing about the CLI or a future web
adapter. It takes a Source and returns one TrackResult per downloaded Track.

Flow (ticket #2): download → fingerprint → album waterfall → confidence gate →
write. Each stage is its own function so later tickets extend one seam without
touching the others: #3/#4 grow ``_album_waterfall``, #5 fills ``_confidence_gate``,
#9 grows ``_write``. The skeleton's stages are pass-throughs (ADR-0002).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from muzik.domain import Match, Source, Tags, Track, TrackResult
from muzik.providers import (
    Authority,
    Downloader,
    Fingerprinter,
    Resolver,
    TagWriter,
)


@dataclass(frozen=True)
class Providers:
    """The five injected providers the engine runs against."""

    downloader: Downloader
    fingerprinter: Fingerprinter
    authority: Authority
    resolver: Resolver
    tagwriter: TagWriter


def run(source: Source, providers: Providers) -> list[TrackResult]:
    """Process a Source end to end, returning one result per Track.

    The per-Track pipeline lives in ``_process_track``; this loop is the seam
    #8 replaces with bounded concurrency.
    """
    results: list[TrackResult] = []
    for track in providers.downloader.download(source):
        results.append(_process_track(track, providers))
    return results


def _process_track(track: Track, providers: Providers) -> TrackResult:
    """The pipeline for a single Track: identify → album → gate → write."""
    match = providers.fingerprinter.identify(track)
    if match is None:
        return _review(track, "no fingerprint match")
    tags = _album_waterfall(match, providers)
    tags = _confidence_gate(track, match, tags)
    output_path = _write(track, tags, providers)
    return TrackResult(
        source_url=track.source_url,
        tags=tags,
        output_path=output_path,
        status="tagged",
    )


#: Tokens that mark a fingerprint album as non-canonical (a single / EP / remix)
#: rather than a studio album. Matched against whole words, so "Deep" or "Sleep"
#: don't trip the "ep" marker.
_NON_CANONICAL_MARKERS = frozenset({"single", "ep", "remix", "remixes"})


def _looks_canonical(album: str) -> bool:
    """A studio album, worth keeping as-is? Empty or single/EP/remix albums aren't."""
    if not album or not album.strip():
        return False
    words = set(re.findall(r"[a-z]+", album.lower()))
    return words.isdisjoint(_NON_CANONICAL_MARKERS)


def _album_waterfall(match: Match, providers: Providers) -> Tags:
    """First tier of the album waterfall (ADR-0002, ticket #3).

    Keep the fingerprint's album when it already looks canonical. When it looks
    non-canonical (single / EP / remix) or is missing, ask the Authority for the
    recording's canonical studio album by ISRC and substitute it. A miss (no ISRC,
    or MusicBrainz returns nothing) leaves the album unchanged. #4 adds the
    Resolver tier below this.
    """
    tags = providers.authority.tags_for(match)
    if _looks_canonical(match.album) or not match.isrc:
        return tags
    studio_album = providers.authority.canonical_album(match.isrc)
    if not studio_album:
        return tags
    return replace(tags, album=studio_album)


# --- Confidence gate (ADR-0002, ticket #5) -------------------------------------
#
# The gate guards against a confident-wrong Match by cross-checking it against
# the Source's own title. It runs only on the matched path (a Track with no
# Match is routed to the Review queue upstream). Three outcomes:
#
#   * Agreement  — the Source title echoes the Match  -> verified Tags, no marker.
#   * Disagreement — the Source title names a different "Artist - Title"
#                    -> best-effort provisional Tags parsed from the Source,
#                       marked unverified (`verified=False`). The Match is never
#                       written as truth.
#   * No signal  — the Source title carries no usable identity (empty, or no
#                  "Artist - Title" to contradict with) -> the Match cannot be
#                  confirmed *or* contradicted, so it is kept but left
#                  unverified, pending review.
#
# The "unverified" marker reuses the existing `Tags.verified` bool: True means
# confirmed, False means provisional/unreviewed. No new field is needed.

#: Boilerplate words a YouTube title carries that say nothing about identity.
_NOISE_TOKENS = frozenset(
    {
        "official", "video", "audio", "lyric", "lyrics", "music", "mv",
        "hd", "hq", "4k", "visualizer", "visualiser", "remastered", "explicit",
        "clip", "full", "version",
    }
)

#: Bracketed asides — "(Official Video)", "[Audio]" — stripped before parsing.
_BRACKETS_RE = re.compile(r"[\(\[\{].*?[\)\]\}]")

#: "Artist - Title", split on the first whitespace-fenced hyphen or dash. The
#: artist may be empty (a title with no artist before the dash); the uploader
#: is its fallback. Internal hyphens ("Spider-Man - Theme") survive: the split
#: needs whitespace *after* the dash, which a word-internal hyphen lacks.
_ARTIST_TITLE_RE = re.compile(r"^(?P<artist>.*?)\s*[-‐-―−]\s+(?P<title>.+)$")


def _clean(text: str) -> str:
    """Strip bracketed asides and collapse whitespace."""
    return re.sub(r"\s+", " ", _BRACKETS_RE.sub(" ", text)).strip()


def _identity_tokens(text: str) -> set[str]:
    """Lower-cased, noise-free word set — the identity a title carries."""
    words = re.findall(r"[0-9a-z]+", _clean(text).lower())
    return {w for w in words if w not in _NOISE_TOKENS}


def _agrees(match: Match, source_title: str) -> bool:
    """True when the Source title echoes the Match's own title.

    Order-independent: every meaningful word of the Match title must appear
    among the Source title's words ("Envy" agrees with "Ogi - Envy").
    """
    title_tokens = _identity_tokens(match.title)
    if not title_tokens:
        return False
    return title_tokens <= _identity_tokens(source_title)


def _source_artist(source_title: str) -> str:
    """The artist half of the Source's "Artist - Title", or "" if there is none."""
    parsed = _ARTIST_TITLE_RE.match(_clean(source_title))
    return parsed.group("artist").strip() if parsed else ""


def _artist_corroborates(match: Match, witness_tokens: set[str]) -> bool:
    """True when the Source's artist witness corroborates the Match's artist.

    The second witness the gate needs (ADR-0002): a title can agree by accident
    ("Love" is a common title), so a Match is confirmed only when the Source also
    backs its *artist*. Every meaningful word of the Match's artist must appear in
    the witness. An empty witness (no artist signal) cannot corroborate — that is
    the "no usable signal" case, kept unverified rather than confirmed.
    """
    artist_tokens = _identity_tokens(match.artist)
    if not artist_tokens or not witness_tokens:
        return False
    return artist_tokens <= witness_tokens


#: YouTube's auto-generated artist channels ("Rick Astley - Topic") and label
#: channels ("RickAstleyVEVO") dress the artist name; strip the dressing so the
#: bare artist is left ("Rick Astley").
_TOPIC_SUFFIX_RE = re.compile(r"\s*-\s*topic\s*$", re.IGNORECASE)
_VEVO_SUFFIX_RE = re.compile(r"vevo\s*$", re.IGNORECASE)


def _normalise_uploader(uploader: str) -> str:
    """A channel name reduced to the bare artist: drop "- Topic" / "VEVO"."""
    return _VEVO_SUFFIX_RE.sub("", _TOPIC_SUFFIX_RE.sub("", uploader)).strip()


def _provisional_from_source(source_title: str, fallback_artist: str) -> Tags | None:
    """Best-effort Tags parsed from the Source's own title.

    Recognises "Artist - Title"; when the title carries no artist, ``fallback_artist``
    (the normalised uploader, #11) is used instead. Returns None when the Source
    offers no usable "Artist - Title" identity to contradict the Match with.
    """
    parsed = _ARTIST_TITLE_RE.match(_clean(source_title))
    if parsed is None:
        return None  # No "Artist - Title" structure: nothing to contradict with.
    title = parsed.group("title").strip()
    if not title:
        return None
    artist = parsed.group("artist").strip() or fallback_artist
    return Tags(title=title, artist=artist, album="", verified=False)


def _confidence_gate(track: Track, match: Match, tags: Tags) -> Tags:
    """Confirm the Match against the Source title, or fall back to provisional.

    The Match is verified only when the Source corroborates it on **both** its
    title and its artist (ADR-0002 / #11) — title agreement alone accepted a
    confident-wrong Match whenever the title was a common word.
    """
    uploader_artist = _normalise_uploader(track.uploader)
    witness = _identity_tokens(_source_artist(track.source_title)) | _identity_tokens(
        uploader_artist
    )
    if _agrees(match, track.source_title) and _artist_corroborates(match, witness):
        return replace(tags, verified=True)
    provisional = _provisional_from_source(track.source_title, uploader_artist)
    if provisional is not None:
        return provisional
    # No signal either way: keep the Match, but never stamp it verified.
    return replace(tags, verified=False)


def _write(track: Track, tags: Tags, providers: Providers) -> Path:
    """Write Tags into the Track's file, returning its path.

    Skeleton: default format. #9 adds output-format selection (M4A/MP3 320).
    """
    return providers.tagwriter.write(track, tags)


def _review(track: Track, reason: str) -> TrackResult:
    """A Track that could not be tagged, routed to the Review queue."""
    return TrackResult(
        source_url=track.source_url,
        tags=None,
        output_path=None,
        status="review",
        reason=reason,
    )
