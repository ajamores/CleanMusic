"""Real Resolver — the AI step (Claude Haiku), per ADR-0002.

Its seam exists now; it is not called on the skeleton's happy path. When the
waterfall reaches it, it proposes a canonical album for a Match it could not
otherwise resolve. Minimal prompt, and it declines rather than guesses wildly.
"""

from __future__ import annotations

import json
import re

import anthropic

from muzik.domain import Match, Track

_HAIKU = "claude-haiku-4-5"


class HaikuResolver:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic()

    def resolve(self, track: Track, match: Match | None) -> Match | None:
        if match is None:
            return None
        album = self._album(match.artist, match.title)
        if not album:
            return None
        return Match(
            title=match.title,
            artist=match.artist,
            album=album,
            cover_art=match.cover_art,
            isrc=match.isrc,
            confidence=match.confidence,
        )

    def _album(self, artist: str, title: str) -> str | None:
        resp = self._client.messages.create(
            model=_HAIKU,
            max_tokens=300,
            system=(
                'Given an artist and song, reply with ONLY JSON {"album": str|null}. '
                "album = the studio album this song originally appeared on, or null "
                "if you are unsure. Do not guess wildly."
            ),
            messages=[{"role": "user", "content": f"Artist: {artist}\nSong: {title}\nWhat studio album?"}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(m.group(0) if m else text).get("album")
        except Exception:
            return None
