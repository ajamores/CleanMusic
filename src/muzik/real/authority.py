"""Real Authority — Shazam's own Tags, plus a MusicBrainz album lookup by ISRC.

``tags_for`` sources Tags straight from the Fingerprinter's Match (Shazam's own
metadata, tier 1). ``canonical_album`` is the first tier of the album waterfall
(ADR-0002, ticket #3): given a recording's ISRC, ask MusicBrainz for the canonical
*studio* album and return its title. The Confidence gate that sets ``verified=True``
and the Resolver tier arrive in later tickets; until then Tags are provisional.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import musicbrainzngs

from muzik.domain import Match, Tags

if TYPE_CHECKING:
    from muzik.providers import Authority

musicbrainzngs.set_useragent(
    "muzik", "0.1.0", "https://github.com/armand/muzik"
)


class ShazamOwnAuthority:
    def tags_for(self, match: Match) -> Tags:
        return Tags(
            title=match.title,
            artist=match.artist,
            album=match.album,
            cover_art=match.cover_art,
            verified=False,
        )

    def canonical_album(self, isrc: str | None) -> str | None:
        """The canonical studio album for a recording, by ISRC, or None.

        Returns None on any miss — no ISRC, a 404, a network error, or no official
        studio-album release — so the waterfall leaves the album unchanged instead
        of crashing. A "studio album" is an ``official`` release whose release-group
        is a primary-type ``Album`` with no secondary types (which excludes
        compilations, live albums, soundtracks, remixes, and DJ-mixes).

        Two lookups, because the ISRC entity can't carry release-groups (#45):
        MusicBrainz's ISRC query only accepts ``artists``/``releases``/``isrcs`` as
        includes, so its releases arrive with no ``release-group`` to filter on. So
        the ISRC resolves the recording id, then a single ``browse_releases`` for
        that recording pulls its official album releases *with* their release-groups
        embedded — one extra call, not one per release. musicbrainzngs throttles
        both to MusicBrainz's ~1 request/second on its own.
        """
        if not isrc:
            return None
        try:
            result = musicbrainzngs.get_recordings_by_isrc(isrc)
        except musicbrainzngs.WebServiceError:
            return None

        recordings = result.get("isrc", {}).get("recording-list", [])
        for recording in recordings:
            recording_id = recording.get("id")
            if not recording_id:
                continue  # a recording with no id is a miss, not a crash
            album = self._studio_album_for_recording(recording_id)
            if album is not None:
                return album
        return None

    def canonical_album_for_recording(self, recording_mbid: str | None) -> str | None:
        """The canonical studio album for a MusicBrainz recording id, or None (#51).

        The by-recording entry point ``canonical_album`` reaches after resolving an
        ISRC. AcoustID hands back a recording id directly, so this skips the ISRC
        step and browses that recording's releases straight away — one call, the
        same studio-album filter and never-crash contract as the ISRC path.
        """
        if not recording_mbid:
            return None
        return self._studio_album_for_recording(recording_mbid)

    def _studio_album_for_recording(self, recording_id: str) -> str | None:
        """The first studio album among a recording's official album releases, or
        None. Browses releases *with* release-groups so the studio-album filter has
        the primary/secondary types the ISRC lookup can't provide (#45)."""
        try:
            # 100 is MusicBrainz's max page. Not paginated deliberately: after the
            # official-album filter a single recording having >100 album releases is
            # not a real case, and each extra page is another rate-limited round-trip
            # against a speed-sensitive path — so cap rather than walk every page.
            result = musicbrainzngs.browse_releases(
                recording=recording_id,
                includes=["release-groups"],
                release_type=["album"],
                release_status=["official"],
                limit=100,
            )
        except musicbrainzngs.WebServiceError:
            return None

        for release in result.get("release-list", []):
            group = release.get("release-group", {})
            primary = (group.get("primary-type") or group.get("type") or "").lower()
            secondary = group.get("secondary-type-list") or []
            if primary == "album" and not secondary:
                return group.get("title") or release.get("title")
        return None


class RateLimitedAuthority:
    """Wraps an Authority so its network tier stays within a rate limit under
    concurrency (ADR-0002: MusicBrainz allows ~1 request/second).

    A playlist batch runs Tracks concurrently (#8), so several threads can reach
    the album lookup at once. Only ``canonical_album`` hits the network, so only
    it is throttled: calls are serialised through a lock and spaced by at least
    ``min_interval`` seconds. ``tags_for`` is pure (Tags from the Match) and passes
    straight through, unthrottled — throttling it would needlessly serialise the
    whole batch.
    """

    def __init__(
        self,
        inner: "Authority",
        min_interval: float = 1.0,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def tags_for(self, match: Match) -> Tags:
        return self._inner.tags_for(match)

    def canonical_album(self, isrc: str | None) -> str | None:
        return self._throttled(lambda: self._inner.canonical_album(isrc))

    def canonical_album_for_recording(self, recording_mbid: str | None) -> str | None:
        # AcoustID's by-recording album lookup (#51) hits the same MusicBrainz
        # service, so it shares the one rate limiter — the two never race.
        return self._throttled(
            lambda: self._inner.canonical_album_for_recording(recording_mbid)
        )

    def _throttled(self, call: Callable[[], str | None]) -> str | None:
        # Holding the lock across the inner call keeps two MusicBrainz requests
        # from ever being in flight together; the spacing keeps successive calls
        # under the rate limit even when the pool has work queued behind them.
        with self._lock:
            wait = self._next_allowed - self._clock()
            if wait > 0:
                self._sleep(wait)
            try:
                return call()
            finally:
                self._next_allowed = self._clock() + self._min_interval
