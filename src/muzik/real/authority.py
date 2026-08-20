"""Real Authority — skeleton pass-through from the Fingerprinter's Match.

Ticket #2 sources Tags straight from Shazam's own metadata. The verified
waterfall (Shazam-own → MusicBrainz → Resolver) and the Confidence gate that
sets `verified=True` arrive in later tickets (ADR-0002); until then Tags are
provisional.
"""

from __future__ import annotations

from muzik.domain import Match, Tags


class ShazamOwnAuthority:
    def tags_for(self, match: Match) -> Tags:
        return Tags(
            title=match.title,
            artist=match.artist,
            album=match.album,
            cover_art=match.cover_art,
            verified=False,
        )
