"""Real Fingerprinter — identifies a Track via Shazam (shazamio).

shazamio is async; the seam is sync, so this bridges with asyncio.run. Tags and
cover art are taken from Shazam's own result (ADR-0002 identifies by fingerprint,
not by parsing the Source title).
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from shazamio import Shazam

from muzik.domain import Match, Track


def _to_wav(src: Path, dst: Path) -> None:
    """Down-convert the first 60s to 16k mono WAV — what the fingerprinter wants."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-t", "60", str(dst)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _dig(payload: dict, key: str) -> str | None:
    """Pull a labelled value (Album, ISRC, ...) out of Shazam's metadata sections."""
    if key.lower() == "isrc" and payload.get("isrc"):
        return payload["isrc"]
    for section in payload.get("sections", []):
        for meta in section.get("metadata", []) or []:
            if str(meta.get("title", "")).lower() == key.lower():
                return meta.get("text")
    return None


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

        shazam_track = out.get("track") or {}
        if not shazam_track:
            return None

        images = shazam_track.get("images", {}) or {}
        return Match(
            title=shazam_track.get("title", ""),
            artist=shazam_track.get("subtitle", ""),
            album=_dig(shazam_track, "Album") or "",
            cover_art=_fetch(images.get("coverarthq") or images.get("coverart")),
            isrc=_dig(shazam_track, "ISRC"),
            confidence=1.0,
        )
