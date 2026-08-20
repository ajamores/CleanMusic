"""Real Authority — Shazam's own Tags, plus a MusicBrainz album lookup by ISRC.

``tags_for`` sources Tags straight from the Fingerprinter's Match (Shazam's own
metadata, tier 1). ``canonical_album`` is the first tier of the album waterfall
(ADR-0002, ticket #3): given a recording's ISRC, ask MusicBrainz for the canonical
*studio* album and return its title. The Confidence gate that sets ``verified=True``
and the Resolver tier arrive in later tickets; until then Tags are provisional.
"""

from __future__ import annotations

import musicbrainzngs

from muzik.domain import Match, Tags

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
        """
        if not isrc:
            return None
        try:
            result = musicbrainzngs.get_recordings_by_isrc(
                isrc,
                includes=["releases"],
                release_type=["album"],
                release_status=["official"],
            )
        except musicbrainzngs.WebServiceError:
            return None

        recordings = result.get("isrc", {}).get("recording-list", [])
        for recording in recordings:
            for release in recording.get("release-list", []):
                group = release.get("release-group", {})
                primary = (group.get("primary-type") or group.get("type") or "").lower()
                secondary = group.get("secondary-type-list") or []
                if primary == "album" and not secondary:
                    return group.get("title") or release.get("title")
        return None
