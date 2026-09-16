"""Real AcoustID Fingerprinter — a second acoustic source for the witness (#51).

Not a blind fallback identifier. Its Match is fed to the ADR-0006 identity witness
as a second, *independent acoustic* claim — derived from the sound, not from the
video's self-asserted title/channel (which an impersonator can type). Shazam stays
primary; AcoustID is the second opinion, deliberately the mirror of cleanmuzik's
AcoustID-first ordering (their ADR-019): AcoustID's tags hydrate through MusicBrainz
(rate-limited), so it is kept off Muzik's speed-sensitive common path (#38) and only
consulted on the witness's own triggers — the uncorroborated path and the
Shazam-miss path.

AcoustID returns a MusicBrainz *recording id* — carried straight onto the Match, so
the album waterfall hydrates the album through MusicBrainz (#45) only for a Match it
actually tags (the primary), never for a second opinion the witness reads then
discards. So the adapter itself makes no album/ISRC lookup: it identifies, nothing
more.

Needs ``fpcalc`` (Chromaprint) on PATH and an AcoustID API key (``ACOUSTID_API_KEY``).
Absent the key, or on any fingerprint/network error, ``identify`` returns ``None`` —
a miss, never a raise: the batch never blocks (ADR-0002).

``match_fn`` is injected so the offline suite drives the adapter with neither
pyacoustid nor its ``fpcalc`` backend; the default calls ``acoustid.match``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import replace

from muzik.domain import Match, Track

#: AcoustID scores each candidate 0..1 by fingerprint similarity. Below this a
#: candidate is noise, not a match, so the adapter reports a miss rather than feed a
#: weak guess to the witness. This score is used ONLY here, as AcoustID's own
#: match/no-match gate; downstream still treats ``Match.confidence`` as binary
#: (docs/LEARNINGS.md), so a returned Match carries ``confidence=1.0`` like Shazam's.
_MIN_SCORE = 0.5

#: One AcoustID candidate: (score, MusicBrainz recording id, title, artist). Any
#: field but the score may be ``None`` when AcoustID has the fingerprint but no
#: linked metadata — the adapter skips such candidates (no title = nothing to tag).
_Candidate = tuple[float | None, str | None, str | None, str | None]


class AcoustIdFingerprinter:
    """Identify a Track by its Chromaprint fingerprint via the AcoustID service."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        match_fn: Callable[[str, str], Iterable[_Candidate]] | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("ACOUSTID_API_KEY", "")
        self._match_fn = match_fn or _acoustid_match

    def identify(self, track: Track) -> Match | None:
        """The best AcoustID candidate as a Match, or ``None`` on a miss.

        On a top-score tie the Match carries the other tied candidates on ``tied``
        (#87); the engine, which owns identity agreement, resolves which one to trust.

        ``None`` — not a raise — for a missing key, a missing ``fpcalc`` backend, a
        fingerprint or network error, or no candidate scoring above the floor. The
        witness then simply has no second opinion, and the batch runs on.
        """
        if not self._api_key:
            return None
        try:
            top = self._top_candidates(str(track.audio_path))
        except Exception:
            return None  # missing fpcalc, unreadable audio, network — a miss, not a raise
        if not top:
            return None
        first, *others = (_to_match(candidate) for candidate in top)
        return replace(first, tied=tuple(others))

    def _top_candidates(self, audio_path: str) -> list[_Candidate]:
        """Every candidate sharing the top score that clears the floor and carries a title.

        ``acoustid.match`` already yields candidates best-score-first, but this finds
        the max explicitly so an unsorted injected ``match_fn`` behaves too. A
        candidate with no title is skipped — there would be nothing to tag or witness.
        More than one comes back on a tie (#87): AcoustID can't tell those recordings
        apart, so the adapter reports them all rather than let response order pick.
        """
        top: list[_Candidate] = []
        for score, recording_id, title, artist in self._match_fn(self._api_key, audio_path):
            if score is None or score < _MIN_SCORE or not title:
                continue
            candidate = (score, recording_id, title, artist)
            if not top or score > (top[0][0] or 0.0):
                top = [candidate]
            elif score == top[0][0]:
                top.append(candidate)
        return top


def _to_match(candidate: _Candidate) -> Match:
    """One AcoustID candidate as a Match — identity and recording id, nothing more."""
    _score, recording_id, title, artist = candidate
    return Match(
        title=title or "",
        artist=artist or "",
        album="",  # AcoustID names no album; the album waterfall fills it (#45)
        recording_mbid=recording_id,  # → the waterfall's MusicBrainz tier, primary only
        confidence=1.0,
    )


def _acoustid_match(api_key: str, audio_path: str) -> Iterable[_Candidate]:
    """AcoustID candidates for an audio file — the real Chromaprint + web backend.

    Lazily imports ``acoustid`` (pyacoustid) so the offline suite, which injects a
    fake ``match_fn``, needs neither the library nor its ``fpcalc`` backend.
    """
    import acoustid

    return acoustid.match(api_key, audio_path, meta=["recordings"], parse=True)
