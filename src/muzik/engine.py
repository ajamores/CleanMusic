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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from muzik.artist import place_feature_credit
from muzik.domain import (
    IdentityRuling,
    IdentityVerdict,
    Match,
    MatchConflict,
    PlaylistEntry,
    ReviewAction,
    ReviewDecision,
    ReviewItem,
    Source,
    Tags,
    Track,
    TrackResult,
)
from muzik.providers import (
    Authority,
    Downloader,
    Fingerprinter,
    PlaylistWriter,
    Resolver,
    ReviewPrompter,
    ReviewQueue,
    TagWriter,
    ThumbnailFetcher,
)


class _NullReviewQueue:
    """Discards enqueued items. The default when a caller opts out of a queue.

    Real runs wire a persisted queue (``cli.py``); tests that assert queue
    contents inject a fake. This default keeps callers that don't care about the
    queue from having to construct one.
    """

    def enqueue(self, item: ReviewItem) -> None:  # noqa: D102
        pass


class _NullPlaylistWriter:
    """Writes no playlist file. The default when a caller opts out (single-mode
    runs, and tests that don't assert a ``.m3u8``). Real ``--playlist`` runs wire
    the M3U8 writer in ``cli.py``.
    """

    #: Always None — this writer never produces a file (part of the seam contract).
    last_written: Path | None = None

    def write(self, title: str, entries: list[PlaylistEntry]) -> Path | None:  # noqa: D102
        return None


class _NullFingerprinter:
    """Identifies nothing — the default second acoustic source (#51).

    Keeps the AcoustID witness (ADR-0006) inert unless a caller injects a real
    second fingerprinter, so a Track is only ever cross-checked against a source a
    caller opted into. Real runs wire ``AcoustIdFingerprinter`` (``cli.py``); tests
    inject a fake. Returning ``None`` (a miss) means the witness sees only the
    primary Shazam claim — exactly the pre-#51 behaviour.
    """

    def identify(self, track: Track) -> Match | None:  # noqa: D102
        return None


class _NullThumbnailFetcher:
    """Fetches nothing — the default when a caller wires no thumbnail fallback.

    Keeps the artwork fallback (#52) inert unless a real fetcher is injected, so a
    Track's cover art is only ever filled from a fetcher a caller opted into. Real
    runs wire ``HttpThumbnailFetcher`` (``cli.py``); tests inject a fake.
    """

    def fetch(self, url: str) -> bytes | None:  # noqa: D102
        return None


@dataclass(frozen=True)
class Providers:
    """The injected providers the engine runs against."""

    downloader: Downloader
    fingerprinter: Fingerprinter
    authority: Authority
    resolver: Resolver
    tagwriter: TagWriter
    review_queue: ReviewQueue = field(default_factory=_NullReviewQueue)
    playlist_writer: PlaylistWriter = field(default_factory=_NullPlaylistWriter)
    thumbnail_fetcher: ThumbnailFetcher = field(default_factory=_NullThumbnailFetcher)
    #: The second acoustic source (AcoustID, #51) — a Fingerprinter consulted only
    #: on the identity witness's own triggers (the uncorroborated path and the
    #: Shazam-miss path), never the corroborated fast path (#38). Defaults to a
    #: no-op, so the second witness stays inert unless a caller wires it.
    acoustid: Fingerprinter = field(default_factory=_NullFingerprinter)


@dataclass(frozen=True)
class BatchSummary:
    """The tally a batch prints when it finishes: verified vs. queued Tracks."""

    verified: int
    queued: int


def summarize(results: list[TrackResult], skipped_count: int = 0) -> BatchSummary:
    """Count verified Tracks vs. those routed to the Review queue.

    A result carries a ``reason`` exactly when it is queued (unidentified, or
    tagged-but-unverified); ``skipped_count`` adds the downloads that never
    became a Track (e.g. age-restricted without cookies).
    """
    queued = sum(1 for r in results if r.reason is not None) + skipped_count
    verified = sum(1 for r in results if r.reason is None)
    return BatchSummary(verified=verified, queued=queued)


#: How many Tracks the batch processes at once by default. Downloads dominate the
#: wall-clock and tagging is cheap (~0.4s/track, ADR-0002); the Authority's own
#: rate limiter — not this bound — is what keeps its network tier within
#: MusicBrainz's 1 req/sec, so a modest default is plenty.
_DEFAULT_CONCURRENCY = 4


def run(
    source: Source, providers: Providers, *, concurrency: int = _DEFAULT_CONCURRENCY
) -> list[TrackResult]:
    """Process a Source end to end, returning one result per downloaded Track.

    A playlist Source expands into many Tracks (#8); once downloaded they are
    independent, so the per-Track pipeline (``_process_track``) runs across a
    bounded thread pool and the results come back in Track order. Every reviewable
    Track — a gate failure, an unidentified Track, or a Downloader skip — is then
    appended to the Review queue with a reason, and the batch runs to completion
    regardless (CONTEXT.md: the batch never blocks).
    """
    tracks = providers.downloader.download(source)
    results = _process_tracks(tracks, providers, concurrency)
    # ``_process_tracks`` guards each Track (#62), so from here every Track has a
    # result — a crash on one becomes its own reviewable failure, never an abort.
    # Enqueue on this thread, not the workers: it keeps the Review queue a single
    # writer (its append needs no lock) and the queue order deterministic —
    # reviewable Tracks in playlist order, then the Downloader's own skips.
    for track, result in zip(tracks, results):
        if result.reason is not None:
            providers.review_queue.enqueue(_review_item(result, track))
    for source_url, reason in providers.downloader.skipped:
        providers.review_queue.enqueue(ReviewItem(source_url=source_url, reason=reason))
    _write_playlist(tracks, results, providers)
    return results


def _write_playlist(
    tracks: list[Track], results: list[TrackResult], providers: Providers
) -> None:
    """Preserve a ``--playlist`` run's grouping as one ``.m3u8`` beside the Tracks (#25).

    Only a real playlist expansion has a title to write under (the Downloader sets
    ``playlist_title`` then, ``None`` in single mode — no list, no file). Lists only
    the Tracks that produced a file, in playlist order, so a fingerprint miss or a
    failed download leaves no dead pointer; ``results`` line up with ``tracks`` by
    index, which is where each Track's duration for ``#EXTINF`` comes from.
    """
    title = providers.downloader.playlist_title
    if title is None:
        return
    entries = [
        PlaylistEntry(
            duration=track.duration,
            artist=result.tags.artist,
            title=result.tags.title,
            path=result.output_path,
        )
        for track, result in zip(tracks, results)
        if result.output_path is not None and result.tags is not None
    ]
    providers.playlist_writer.write(title, entries)


def _process_tracks(
    tracks: list[Track], providers: Providers, concurrency: int
) -> list[TrackResult]:
    """Run the per-Track pipeline over a bounded thread pool, preserving order.

    ``ThreadPoolExecutor.map`` yields results in submission order, so the returned
    list lines up with ``tracks`` regardless of which finished first. An empty
    playlist needs no pool. Each Track is guarded (#62): an exception from any
    stage becomes that Track's own failed result rather than propagating — with
    the Review queue and ``.m3u8`` written only after processing, one corrupt
    file must not discard a whole batch's identification work.
    """
    if not tracks:
        return []
    workers = max(1, min(concurrency, len(tracks)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda track: _process_track_guarded(track, providers), tracks))


def _process_track_guarded(track: Track, providers: Providers) -> TrackResult:
    """``_process_track``, with any escaping exception captured as a failed result.

    The failure keeps the Track's identity and names the exception, and ``run``
    routes it to the Review queue like any other reviewable result — surfaced to
    the user at the end of the batch, never silently dropped. Nothing is claimed
    written (``tags``/``output_path`` are None): a crash may have struck at any
    stage, including mid-write.
    """
    try:
        return _process_track(track, providers)
    except Exception as exc:
        return TrackResult(
            source_url=track.source_url,
            tags=None,
            output_path=None,
            status="review",
            reason=f"failed: {type(exc).__name__}: {exc}",
        )


def _process_track(track: Track, providers: Providers) -> TrackResult:
    """The pipeline for a single Track: identify → album → gate → write.

    Shazam is the primary identifier. When it hits, AcoustID (#51) may be consulted
    inside the gate as a *second* acoustic witness — but only on the uncorroborated
    path, never the corroborated fast path (#38). When Shazam misses entirely,
    ``_rescue_or_review`` tries AcoustID before falling back to a best-effort Review.
    """
    match = providers.fingerprinter.identify(track)
    if match is None:
        return _rescue_or_review(track, providers)
    return _tag_matched(track, match, providers, second_source=providers.acoustid)


def _rescue_or_review(track: Track, providers: Providers) -> TrackResult:
    """Shazam found nothing — try the second acoustic source before giving up (#51).

    AcoustID and Shazam have complementary blind spots, so a Shazam miss is exactly
    where a second fingerprinter earns its cost (this path was already destined for
    Review — a "try harder" replacing a "give up", #38). A hit becomes *the* Match,
    run through the same album waterfall and gate as a Shazam Match; with Shazam
    absent there is no other acoustic claim, so the gate consults no second source.
    A miss (both fingerprinters silent) falls to the best-effort Review path.
    """
    rescued = providers.acoustid.identify(track)
    if rescued is None:
        return _best_effort_review(track, "no fingerprint match", providers)
    return _tag_matched(track, rescued, providers, second_source=None)


def _tag_matched(
    track: Track,
    match: Match,
    providers: Providers,
    *,
    second_source: Fingerprinter | None,
) -> TrackResult:
    """Album → gate → thumbnail → write for an identified Track.

    Shared by the Shazam-hit and AcoustID-rescue paths. ``second_source`` is the
    fingerprinter the gate may consult as a second acoustic witness on the
    uncorroborated path (#51) — Shazam's partner AcoustID when Shazam is primary,
    ``None`` when AcoustID is itself the primary (a rescue: no other source remains).
    """
    tags = _album_waterfall(track, match, providers)
    tags, reason, conflict = _confidence_gate(
        track, match, tags, providers.resolver, second_source
    )
    tags = _with_thumbnail_fallback(track, tags, providers)
    tags, output_path = _write(track, tags, providers)
    return TrackResult(
        source_url=track.source_url,
        tags=tags,
        output_path=output_path,
        status="tagged",
        reason=reason,
        conflict=conflict,
    )


def _review_item(result: TrackResult, track: Track) -> ReviewItem:
    """The Review-queue entry for a reviewable result (``reason`` is set).

    Carries ``track.audio_path`` so the clear pass (#7) can find the file on disk
    even when nothing was written (a fingerprint miss has no ``output_path``).
    """
    assert result.reason is not None
    return ReviewItem(
        source_url=result.source_url,
        reason=result.reason,
        tags=result.tags,
        output_path=result.output_path,
        audio_path=track.audio_path,
        conflict=result.conflict,
    )


# --- Clearing the Review queue (ticket #7) -------------------------------------
#
# After a batch, the user works through the queue one entry at a time. This side
# is interface-agnostic too (ADR-0001): it drives a ReviewPrompter seam rather
# than reading input, so the CLI and a future web adapter share it. Each entry is
# accepted (verify its provisional Tags), tagged manually (user-supplied Tags),
# re-identified from a hint, or skipped; a cleared entry is dropped from the queue.


@dataclass(frozen=True)
class ReviewOutcome:
    """What became of one Review-queue entry during a clear pass.

    ``cleared`` is True when the entry was tagged and dropped from the queue;
    ``result`` is the write that tagged it (None for a skip or a failed hint).
    """

    item: ReviewItem
    action: ReviewAction
    cleared: bool
    result: TrackResult | None


def clear_review_queue(
    providers: Providers, prompter: ReviewPrompter
) -> list[ReviewOutcome]:
    """Work through the Review queue, applying the user's choice to each entry.

    Reads every entry, asks ``prompter`` what to do, applies it, and rewrites the
    queue with the survivors — the entries left un-cleared (skipped, or a hint
    that failed to re-identify). The queue is rewritten once, at the end.
    """
    outcomes: list[ReviewOutcome] = []
    survivors: list[ReviewItem] = []
    for item in providers.review_queue.items():
        decision = prompter.decide(item)
        result = _apply_review_decision(item, decision, providers)
        cleared = result is not None and result.reason is None
        outcomes.append(
            ReviewOutcome(item=item, action=decision.action, cleared=cleared, result=result)
        )
        if not cleared:
            survivors.append(item)
    providers.review_queue.replace_all(survivors)
    return outcomes


def _apply_review_decision(
    item: ReviewItem, decision: ReviewDecision, providers: Providers
) -> TrackResult | None:
    """Carry out one decision, returning the write it produced (None if none)."""
    if decision.action == "skip":
        return None
    if decision.action == "accept":
        if item.tags is None:
            raise ValueError("cannot accept an entry that has no provisional Tags")
        return _tag_from_review(item, replace(item.tags, verified=True), providers)
    if decision.action == "manual":
        if decision.tags is None:
            raise ValueError("a manual decision must carry the Tags to write")
        return _tag_from_review(item, replace(decision.tags, verified=True), providers)
    if decision.action == "hint":
        if not decision.hint:
            raise ValueError("a hint decision must carry the corrected title")
        return _reidentify(item, decision.hint, providers)
    raise ValueError(f"unknown review action: {decision.action!r}")


def _tag_from_review(item: ReviewItem, tags: Tags, providers: Providers) -> TrackResult:
    """Write ``tags`` (verified) into the queued Track's file and return the result."""
    track = _track_from_item(item)
    tags, output_path = _write(track, tags, providers)
    return TrackResult(
        source_url=item.source_url,
        tags=tags,
        output_path=output_path,
        status="tagged",
        reason=None,
    )


def _reidentify(item: ReviewItem, hint: str, providers: Providers) -> TrackResult:
    """Re-identify a queued Track from the user's hint, then tag and dequeue it.

    A hint is the user asserting the correct "Artist - Title" — the authority a
    review exists to supply. Identification is re-run over it: the audio is
    re-fingerprinted, and when the fingerprint now agrees with the hint its Match
    is kept (so its cover art and ISRC come along). Otherwise — a fingerprint miss
    (the commonest review reason, and the case a hint most needs to rescue), or a
    fingerprint that contradicts the user — the hint itself seeds the identity.
    Either way the album waterfall fills the album and the Tags are written
    verified. Only a hint with no usable title fails, leaving the entry queued.
    """
    track = replace(_track_from_item(item), source_title=hint)
    seed = _match_from_hint(hint)
    if seed is None:
        return _best_effort_review(track, "a hint needs a title to re-identify", providers)
    match = providers.fingerprinter.identify(track)
    if match is None or not _hint_corroborates(match, hint):
        match = seed
    tags = replace(_album_waterfall(track, match, providers), verified=True)
    tags, output_path = _write(track, tags, providers)
    return TrackResult(
        source_url=track.source_url,
        tags=tags,
        output_path=output_path,
        status="tagged",
        reason=None,
    )


def _match_from_hint(hint: str) -> Match | None:
    """A user-asserted identity from a hint: "Artist - Title", or a bare title."""
    parsed = _ARTIST_TITLE_RE.match(_clean(hint))
    if parsed is not None:
        title, artist = parsed.group("title").strip(), parsed.group("artist").strip()
    else:
        title, artist = _clean(hint), ""
    if not title:
        return None
    return Match(title=title, artist=artist, album="", confidence=1.0)


def _hint_corroborates(match: Match, hint: str) -> bool:
    """True when a re-fingerprinted Match agrees with the hint on title and artist."""
    witness = _identity_tokens(_source_artist(hint))
    return _agrees(match, hint) and _artist_corroborates(match, witness)


def _track_from_item(item: ReviewItem) -> Track:
    """Reconstruct the Track a queue entry refers to, for tagging/re-identifying."""
    audio_path = item.audio_path or item.output_path
    if audio_path is None:
        raise ValueError(
            f"{item.source_url} has no file on disk to tag or re-identify"
        )
    return Track(source_url=item.source_url, audio_path=audio_path)


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


def _album_waterfall(track: Track, match: Match, providers: Providers) -> Tags:
    """The album waterfall (ADR-0002, tickets #3 + #4), consulted in order.

    Keep the fingerprint's album when it already looks canonical. Otherwise
    (non-canonical — single / EP / remix — or missing) descend the waterfall:

      1. the Authority's canonical studio album from MusicBrainz — by ISRC (Shazam's
         handle), or by recording id when the identifier gave one directly instead
         (AcoustID, #51); skipped when the Match carries neither;
      2. the Resolver (Claude Haiku, #4), the last resort, consulted only when
         the album is *still* unresolved after the catalogs.

    Each tier fires only while the album is unresolved, so a canonical album — or
    one MusicBrainz supplies — never reaches the Resolver. A tier that yields
    nothing leaves the album unchanged and the next tier tries.
    """
    tags = providers.authority.tags_for(match)
    if _looks_canonical(match.album):
        return tags
    if match.isrc:
        studio_album = providers.authority.canonical_album(match.isrc)
        if studio_album:
            return replace(tags, album=studio_album)
    if match.recording_mbid:
        studio_album = providers.authority.canonical_album_for_recording(match.recording_mbid)
        if studio_album:
            return replace(tags, album=studio_album)
    resolved = providers.resolver.resolve(track, match)
    if resolved is not None and resolved.album:
        return replace(tags, album=resolved.album)
    return tags


# --- Confidence gate (ADR-0002, ticket #5; identity witness, #38 / ADR-0006) ---
#
# The gate guards against a confident-wrong Match. It runs only on the matched
# path (a Track with no Match is routed to the Review queue upstream). Outcomes:
#
#   * Corroborated — the Source's own title echoes the Match on BOTH its title and
#                    its artist -> verified Tags, no marker, and NO AI call. This
#                    is the common case, kept off the AI path for speed (#38).
#   * Uncorroborated-but-not-contradicted — the title echoes the Match, but the
#                    Source names no artist of its own to back it (the artist rests
#                    only on the channel, or on nothing). Shazam confidence is
#                    binary (docs/LEARNINGS.md), so there is no bar to lean on;
#                    instead the Resolver rules on identity over the full evidence
#                    (fingerprint + title/channel/description/tags/thumbnail,
#                    ADR-0006). `consistent` -> verified; `inconsistent`/`unsure`
#                    -> kept unverified, Review. A witness failure/timeout degrades
#                    to `unsure` (ADR-0002: the batch never blocks).
#   * Contradicted — the Source names a different "Artist - Title", or its own
#                    artist names someone else -> best-effort provisional Tags
#                    parsed from the Source, unverified. No AI call: the Source
#                    actively disagrees, which a witness can't overturn.
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

#: Grammatical stopwords that never distinguish one recording from another. Dropped
#: alongside the noise words so a lone "The"/"is"/"and" difference between the
#: fingerprint's title and the Source's doesn't sink title agreement (#41) — e.g.
#: fingerprint "The Vibes Is Right" vs Source "Vibes Is Right". Kept deliberately
#: small: only words with no identifying power, so real titles aren't hollowed out.
_STOPWORDS = frozenset({"the", "a", "an", "and", "of", "is"})

#: Everything the identity tokeniser strips: boilerplate and grammatical filler.
_NON_IDENTITY_TOKENS = _NOISE_TOKENS | _STOPWORDS

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
    return {w for w in words if w not in _NON_IDENTITY_TOKENS}


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


def _confidence_gate(
    track: Track,
    match: Match,
    tags: Tags,
    resolver: Resolver,
    second_source: Fingerprinter | None,
) -> tuple[Tags, str | None, MatchConflict | None]:
    """Confirm the Match against the Source, or fall back to provisional.

    Returns the Tags to write, a Review-queue reason (``None`` only when the Match
    is verified), and — on a provisional outcome — a ``MatchConflict`` recording
    the rejected Match and the witnesses it failed against (#24).

    Three paths (see the header comment). The Match is verified outright only when
    the Source's own title corroborates it on **both** title and artist — a witness
    a channel can't fake, and the common case, so it takes no AI call and no second
    fingerprint (#38). When the title echoes the Match but its own title doesn't
    corroborate the artist, the identity rests on the channel (assertable), on
    nothing, or on a *parse* that may be reversed or dressed — a dumb "Artist -
    Title" split is not a reliable contradiction signal (#42). There the Resolver is
    consulted as an independent identity witness (ADR-0006), replacing the retired
    confidence bar (Shazam confidence is binary — docs/LEARNINGS.md), and — this is
    where #51 adds cost — the ``second_source`` (AcoustID) is fingerprinted so the
    witness weighs a second *acoustic* claim, not just the video's metadata. Only a
    Source whose title names a *different* recording is kept provisional without an
    AI call or a second fingerprint — a real contradiction, which also bounds the
    added cost (#38).
    """
    title_witness = _identity_tokens(_source_artist(track.source_title))
    title_agrees = _agrees(match, track.source_title)
    corroborated_by_title = _artist_corroborates(match, title_witness)

    # Corroborated by the Source's own title (title + artist): verified, no AI,
    # no second fingerprint. The common case, kept off both cost paths (#38).
    if title_agrees and corroborated_by_title:
        return replace(tags, verified=True), None, None

    # Title echoes the Match, but the Source's own title doesn't independently back
    # the artist — no artist witness, or a parse that may be reversed/dressed (a
    # naive "Artist - Title" split can't be trusted as a contradiction, #42).
    # Consult the identity witness instead of the (retired) confidence bar (#38),
    # and give it a second acoustic opinion (AcoustID, #51) when one is available.
    # On a `consistent` verdict the fingerprint's tags (already in `tags`) are
    # written verified — never the possibly-reversed Source parse.
    if title_agrees:
        second = second_source.identify(track) if second_source is not None else None
        ruling = _identity_ruling(track, match, second, resolver)
        if ruling.verdict == "consistent":
            return replace(tags, verified=True), None, None
        return _unverified(tags, track, match, ruling.verdict, ruling.rationale)

    # The title names a different recording — a real contradiction. Never write the
    # Match as truth; fall back to the Source's own identity, best-effort. No AI.
    return _unverified(tags, track, match, None)


def _unverified(
    tags: Tags,
    track: Track,
    match: Match,
    verdict: IdentityVerdict | None,
    rationale: str = "",
) -> tuple[Tags, str, MatchConflict]:
    """The provisional outcome: Source-parsed Tags, or the kept-but-unverified Match.

    ``verdict`` is the identity witness's ruling when it was consulted (``None`` on
    the contradicted path, where no witness ran) — it shapes only the explanation.
    ``rationale`` is the witness's own sentence for that ruling (#74), carried onto
    the conflict so the Review output can show the reasoning, not just the verdict.
    """
    uploader_artist = _normalise_uploader(track.uploader)
    conflict = MatchConflict(
        heard=match,
        source_artist=_source_artist(track.source_title),
        # The normalised channel — the artist witness the gate actually weighed
        # ("AdeleVEVO" → "Adele", "… - Topic" → ""). Storing the raw channel could
        # show a "video/channel says:" witness the ``why`` line calls absent.
        uploader=uploader_artist,
        why=_conflict_why(match, track, verdict),
        witness_rationale=rationale,
    )
    provisional = _provisional_from_source(track.source_title, uploader_artist)
    if provisional is not None:
        return (
            provisional,
            "unverified: provisional Tags from the Source, Match not corroborated",
            conflict,
        )
    # No usable Source identity: keep the Match, but never stamp it verified.
    if verdict == "inconsistent":
        reason = "unverified: the identity witness found the Match inconsistent with the Source"
    else:
        reason = "unverified: no independent witness to confirm the Match"
    return replace(tags, verified=False), reason, conflict


def _conflict_why(match: Match, track: Track, verdict: IdentityVerdict | None) -> str:
    """A short line naming why the gate kept the Track provisional (#24).

    Either the Source's title names a different recording (``verdict`` is ``None`` — the
    witness never ran), or the title echoed the Match but the identity witness would
    not confirm it (#42): its ruling — ``inconsistent`` or, failing that, ``unsure``.
    """
    if not _agrees(match, track.source_title):
        return "title didn't match, kept provisional"
    if verdict == "inconsistent":
        return "the identity witness ruled the Match inconsistent with the video, kept provisional"
    # verdict == "unsure": a `consistent` ruling verifies, so this is the only
    # remaining case once the title agrees (#42).
    return "the identity witness couldn't confirm the Match, kept provisional"


def _identity_ruling(
    track: Track, match: Match, second: Match | None, resolver: Resolver
) -> IdentityRuling:
    """Ask the Resolver to witness the Match's identity, degrading safely (ADR-0002).

    ``second`` is the second acoustic identification (AcoustID, #51) when one ran,
    ``None`` otherwise; the witness weighs it as corroborating evidence. The whole
    ruling comes back — verdict and the witness's one-sentence rationale (#74).
    Any failure or timeout in the AI call is treated as ``unsure`` — the Track
    stays unverified and goes to Review, but the batch never blocks. (The real
    Resolver also degrades internally; this is the belt-and-braces boundary so a
    misbehaving provider can't abort a batch.)
    """
    try:
        return resolver.witness_identity(track, match, second)
    except Exception:
        return IdentityRuling(verdict="unsure", rationale="")


def _with_thumbnail_fallback(track: Track, tags: Tags, providers: Providers) -> Tags:
    """Fill empty cover art with the video thumbnail so no file ships bare (#52).

    Purely additive (ADR-0002 note): only when the Tags carry no real ``cover_art``
    *and* the Track names a thumbnail. Real album art is never overridden — the
    confident, correctly-tagged common case is untouched. A fetch miss or timeout
    leaves the Tags bare rather than raising: the same never-block contract as the
    other network tiers. The review-clear paths reconstruct a Track with no
    ``thumbnail_url``, so this is a no-op there — it fills only the batch path.
    """
    if tags.cover_art is not None or not track.thumbnail_url:
        return tags
    data = providers.thumbnail_fetcher.fetch(track.thumbnail_url)
    if data is None:
        return tags
    return replace(tags, cover_art=data)


def _source_only_tags(track: Track) -> Tags | None:
    """Best-effort Tags from the Source alone, for a Track with no Match (#52).

    Prefer the Source's own "Artist - Title" split (the same parse the gate's
    provisional path uses, ``_provisional_from_source``); when the title carries no
    such structure, fall back to the whole title with the normalised channel as
    artist. That whole-title tier is deliberately *extra* here and absent from the
    gate's ``_unverified``: the gate always has a Match to keep when the Source
    won't parse, but a no-Match Track has nothing else — so writing the raw title
    is the only alternative to shipping bare. ``None`` only when the Source names
    no title at all, and then there is nothing to write.
    """
    uploader_artist = _normalise_uploader(track.uploader)
    provisional = _provisional_from_source(track.source_title, uploader_artist)
    if provisional is not None:
        return provisional
    title = _clean(track.source_title)
    if not title:
        return None
    return Tags(title=title, artist=uploader_artist, album="", verified=False)


def _write(track: Track, tags: Tags, providers: Providers) -> tuple[Tags, Path]:
    """Canonicalise the artist/title Tags, write, and return them with their path.

    The single choke point every write funnels through — the batch's matched and
    best-effort paths and the review-clear paths alike — so canonicalising here
    covers verified and provisional Tags in one place, with no path able to skip it.
    ``place_feature_credit`` both applies #47's in-place artist tidy *and* moves a
    featured-artist clause out of the artist field into the title (#56), so the
    artist stays primary-only. The possibly-rewritten Tags are returned so each
    caller reports what was actually written: the file, the Review queue entry, and a
    ``--playlist`` run's ``.m3u8`` all carry the same canonical title and artist.
    """
    title, artist = place_feature_credit(tags.title, tags.artist)
    tags = replace(tags, title=title, artist=artist)
    return tags, providers.tagwriter.write(track, tags)


def _best_effort_review(track: Track, reason: str, providers: Providers) -> TrackResult:
    """A Track with no fingerprint Match — tagged best-effort, then routed to Review.

    No Track ships bare (#52): rather than write nothing, fill Tags from the Source
    itself (title/artist) plus the thumbnail as art, and still enqueue the result
    to Review as an unverified guess (this is the ADR-0002 relaxation — an
    unidentified Track is now tagged best-effort, no longer left untagged). When
    the Source offers no usable title to write (``_source_only_tags`` is ``None``),
    nothing is written and the entry is queued with no Tags, as before.
    """
    tags = _source_only_tags(track)
    if tags is None:
        return TrackResult(
            source_url=track.source_url,
            tags=None,
            output_path=None,
            status="review",
            reason=reason,
        )
    tags = _with_thumbnail_fallback(track, tags, providers)
    tags, output_path = _write(track, tags, providers)
    return TrackResult(
        source_url=track.source_url,
        tags=tags,
        output_path=output_path,
        status="tagged",
        reason=reason,
    )
