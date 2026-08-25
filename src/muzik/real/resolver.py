"""Real Resolver — the AI step (Claude Haiku), per ADR-0002 and ADR-0006.

Two capabilities over one Haiku client:

* ``resolve`` — the album waterfall's last resort (ADR-0002): propose a canonical
  studio album for a Match the catalogs couldn't place. It declines rather than
  guess wildly.
* ``witness_identity`` — the identity witness (ADR-0006, #38): reason over the
  fingerprint Match *and* the Track's full evidence (title, channel, description,
  tags, and the thumbnail — a multimodal call; Haiku reads images) and rule
  whether the identification is consistent. This is what lets the Confidence gate
  verify on an independent witness rather than on Shazam alone.

Both degrade rather than raise: a batch never blocks (ADR-0002). ``witness_identity``
returns an ``unsure`` verdict on any failure or timeout.
"""

from __future__ import annotations

import base64
import json
import re
from typing import get_args

import anthropic

from muzik.domain import IdentityRuling, IdentityVerdict, Match, Track
from muzik.real.images import fetch_thumbnail

_HAIKU = "claude-haiku-4-5"

#: How long to wait on the witness's *API call* before degrading to ``unsure``
#: (ADR-0002). The thumbnail fetch that precedes it is bounded separately (by the
#: shared ``images.fetch_thumbnail``), so the whole witness is bounded by their
#: sum — the real per-uncorroborated-Track worst case (#38, speed-sensitive). Both
#: legs degrade rather than raise, so a slow provider never stalls a batch.
_WITNESS_TIMEOUT_S = 20.0

#: Cap on how much description text to send — enough to identify, without paying
#: for a whole video's worth of boilerplate on every witnessed Track.
_DESCRIPTION_LIMIT = 2000

#: The verdicts the witness may return; anything else degrades to ``unsure``.
#: Derived from the domain Literal so the two never drift.
_VERDICTS: frozenset[str] = frozenset(get_args(IdentityVerdict))


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
        try:
            return _json_object(_first_text(resp)).get("album")
        except Exception:
            return None

    def witness_identity(
        self, track: Track, match: Match, second: Match | None = None
    ) -> IdentityRuling:
        """Rule on whether ``match`` fits the Track's own evidence (ADR-0006).

        Reasons over the fingerprint identity and the Source's metadata — including
        the thumbnail when one is available. ``second`` is an optional second,
        independent acoustic identification (AcoustID, #51) weighed as evidence:
        two acoustic sources agreeing is stronger than the video's own title/channel,
        and their disagreement is a signal in itself. Any failure or timeout degrades
        to ``unsure`` so the batch never blocks (ADR-0002).
        """
        try:
            return self._witness(track, match, second)
        except Exception:
            return IdentityRuling(verdict="unsure", rationale="witness call failed")

    def _witness(self, track: Track, match: Match, second: Match | None) -> IdentityRuling:
        content: list[dict] = [{"type": "text", "text": _witness_prompt(track, match, second)}]
        image = _fetch_image(track.thumbnail_url)
        if image is not None:
            data, media_type = image
            content.insert(
                0,
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data},
                },
            )
        resp = self._client.with_options(timeout=_WITNESS_TIMEOUT_S).messages.create(
            model=_HAIKU,
            max_tokens=300,
            system=(
                "You are an identity checker for a music tagger. You are given an "
                "acoustic-fingerprint identification of a Track (the artist and song "
                "a fingerprint service returned) and the ORIGINAL video's own "
                "evidence: its title, channel, description, tags, and thumbnail. "
                "Decide whether the fingerprint identification is CONSISTENT with "
                "that evidence — i.e. the video really is that artist's recording of "
                "that song, not a different song, a cover, or an impersonator "
                "channel dressed in the artist's name. "
                "You may also be given a SECOND, independent acoustic identification "
                "from a different fingerprint service. Two acoustic sources are "
                "evidence about what the audio actually is — stronger than the "
                "video's own title or channel, which anyone can type. When both "
                "acoustic sources agree, that strongly supports 'consistent'. When "
                "they disagree, judge which (if either) the video's evidence "
                "supports; if neither clearly fits, or you cannot tell, answer "
                "'inconsistent' or 'unsure' so a human reviews it. "
                'Reply with ONLY JSON {"verdict": "consistent"|"inconsistent"|'
                '"unsure", "rationale": str}. Use "unsure" when the evidence is too '
                "thin to tell. Keep the rationale to one short sentence."
            ),
            messages=[{"role": "user", "content": content}],
        )
        return _parse_ruling(_first_text(resp))


def _witness_prompt(track: Track, match: Match, second: Match | None = None) -> str:
    """The text half of the witness call: the fingerprint(s) set against the Source.

    Carries the primary fingerprint identification and, when a second independent
    acoustic source ran (AcoustID, #51), its identification too — so the witness can
    weigh two acoustic claims against the video's own evidence.
    """
    tags = ", ".join(track.tags) if track.tags else "(none)"
    description = track.description.strip()
    if len(description) > _DESCRIPTION_LIMIT:
        description = description[:_DESCRIPTION_LIMIT] + "…"
    second_block = (
        "Second acoustic identification (an independent fingerprinter):\n"
        f"  artist: {second.artist}\n"
        f"  song:   {second.title}\n\n"
        if second is not None
        else ""
    )
    return (
        "Fingerprint identification:\n"
        f"  artist: {match.artist}\n"
        f"  song:   {match.title}\n\n"
        f"{second_block}"
        "Original video evidence:\n"
        f"  title:       {track.source_title}\n"
        f"  channel:     {track.uploader}\n"
        f"  tags:        {tags}\n"
        f"  description: {description or '(none)'}\n\n"
        "Is the fingerprint identification consistent with this video?"
    )


def _first_text(resp) -> str:
    """The first text block of a Messages response, or ``"{}"`` if there is none."""
    return next((b.text for b in resp.content if b.type == "text"), "{}")


def _json_object(text: str) -> dict:
    """Parse the first ``{...}`` object out of a model reply (may raise)."""
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _parse_ruling(text: str) -> IdentityRuling:
    """Parse the model's JSON reply into a ruling, degrading to ``unsure``."""
    try:
        data = _json_object(text)
        verdict = str(data.get("verdict", "")).strip().lower()
        rationale = str(data.get("rationale", "")).strip()
    except Exception:
        return IdentityRuling(verdict="unsure", rationale="unparseable witness reply")
    if verdict not in _VERDICTS:
        return IdentityRuling(verdict="unsure", rationale=rationale or "no verdict")
    return IdentityRuling(verdict=verdict, rationale=rationale)  # type: ignore[arg-type]


def _fetch_image(url: str) -> tuple[str, str] | None:
    """Fetch a thumbnail as (base64 data, media_type) for the multimodal call.

    Thin wrapper over the shared ``fetch_thumbnail`` (#52): the witness needs the
    bytes base64-encoded, the tagging path needs them raw, so the fetch/timeout
    live once in ``images`` and each caller adapts. ``None`` when unavailable —
    the witness then reasons over text alone rather than fail.
    """
    result = fetch_thumbnail(url)
    if result is None:
        return None
    raw, media_type = result
    return base64.standard_b64encode(raw).decode("ascii"), media_type
