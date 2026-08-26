"""Real Fingerprinter — identifies a Track via Shazam (shazamio).

shazamio is async; the seam is sync, so this bridges with asyncio.run. Tags and
cover art are taken from Shazam's own result (ADR-0002 identifies by fingerprint,
not by parsing the Source title), parsed through shazamio's own ``Serialize``
dataclasses rather than hand-rolled dict walking (#58).
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from shazamio import Serialize, Shazam
from shazamio.schemas.models import SongSection, TrackInfo

from muzik.domain import Match, Track


def _to_wav(src: Path, dst: Path) -> None:
    """Down-convert the first 60s to 16k mono WAV — what the fingerprinter wants."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-t", "60", str(dst)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _labelled(info: TrackInfo, label: str) -> str | None:
    """A labelled value (Album, ISRC, ...) from the SONG section's metadata rows.

    Shazam has no named album field anywhere in its response — such values only
    appear as ``SongMetadata`` rows — so a label match remains, but over
    ``Serialize``'s typed dataclasses instead of an untyped dict walk.
    """
    for section in info.sections or []:
        if isinstance(section, SongSection):
            for meta in section.metadata:
                if meta.title.lower() == label.lower():
                    return meta.text
    return None


def _to_match(out: dict) -> Match | None:
    """Parse a raw ``recognize`` response into a Match, or None for a miss.

    ``Serialize.track`` takes the response's ``track`` part (verified live,
    2026-08-26, shazamio 0.8.1). ``Serialize.full_track`` parses the whole
    response too, but its envelope makes unrelated fields fatal — a missing
    ``tagid`` would zero the Match — so the narrower serializer is the safer fit.
    Two fields the serializer does not deliver stay raw-dict reads by their
    stable named keys: ``TrackInfo`` has no isrc field, and its ``photo_url`` is
    declared ``init=False`` so the factory never populates it. A ``track`` the
    serializer rejects degrades to those same raw keys — one drifted corner must
    not zero the whole Match, and the batch never blocks (ADR-0002).
    """
    raw_track = out.get("track") or {}
    if not raw_track:
        return None

    try:
        info = Serialize.track(data=raw_track)
        title = info.title
        artist = info.subtitle
        album = _labelled(info, "Album") or ""
        isrc_row = _labelled(info, "ISRC")
    except Exception:
        title = str(raw_track.get("title") or "")
        artist = str(raw_track.get("subtitle") or "")
        album = ""
        isrc_row = None

    images = raw_track.get("images") or {}
    return Match(
        title=title,
        artist=artist,
        album=album,
        cover_art=_fetch(images.get("coverarthq") or images.get("coverart")),
        isrc=raw_track.get("isrc") or isrc_row,
        confidence=1.0,
    )


def _fetch(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read()
    except Exception:
        return None


class ShazamFingerprinter:
    def identify(self, track: Track) -> Match | None:
        return asyncio.run(self._identify(track))

    async def _identify(self, track: Track) -> Match | None:
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "clip.wav"
            await asyncio.to_thread(_to_wav, track.audio_path, wav)
            try:
                out = await Shazam().recognize(str(wav))
            except Exception:
                return None
        return _to_match(out)
