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
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from shazamio import Serialize, Shazam
from shazamio.schemas.models import SongSection, TrackInfo

from muzik.domain import Match, Track
from muzik.providers import Fingerprinter


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
    """Identify a Track via Shazam. A miss returns ``None``; a *failure* raises.

    The two are deliberately distinct (#63): a genuine miss (Shazam heard nothing
    it knows) is an answer, but a network error or rate-limit is not — swallowing
    it here would make a limited Shazam indistinguishable from a miss and flood
    the Review queue. ``RateLimitedFingerprinter`` (which real runs wrap this in,
    ``cli.py``) owns the retry and the final degrade-to-miss; the engine's
    per-Track guard (#62) is the backstop, so the batch still never blocks.
    """

    #: Ceiling on one recognize round-trip. A healthy call answers in a few
    #: seconds; a rate-limiting Shazam *tarpits* — accepts the connection and
    #: never replies (observed live, #79: all four workers wedged indefinitely,
    #: shazamio itself imposing no timeout). The bound turns that into a raise
    #: the RateLimitedFingerprinter retries and then notes as a miss.
    _RECOGNIZE_TIMEOUT_S = 30.0

    def __init__(self, recognize_timeout: float = _RECOGNIZE_TIMEOUT_S) -> None:
        self._recognize_timeout = recognize_timeout

    def identify(self, track: Track) -> Match | None:
        return asyncio.run(self._identify(track))

    async def _identify(self, track: Track) -> Match | None:
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "clip.wav"
            await asyncio.to_thread(_to_wav, track.audio_path, wav)
            out = await asyncio.wait_for(
                Shazam().recognize(str(wav)), timeout=self._recognize_timeout
            )
        return _to_match(out)


class RateLimitedFingerprinter:
    """Wraps a Fingerprinter so a batch can't fire rapid identify calls, and a
    transient failure is retried instead of flooding the Review queue (#63).

    A ~400-Track batch from 4 workers is exactly the burst pattern that draws a
    rate-limit or temp-ban from Shazam. Calls are spaced by ``min_interval`` at
    their *starts* — unlike ``RateLimitedAuthority``, the lock is not held across
    the call, so identifications still overlap and the pipeline's speed-sensitive
    throughput is capped by the request rate, not serialised.

    A failure (the inner fingerprinter raising — network error, rate-limit) is
    retried up to ``attempts`` times total, sleeping ``backoff`` doubling between
    tries, each retry re-claiming a throttle slot. Exhausted, it degrades to
    ``None`` — the miss path the engine already handles (best-effort Tags +
    Review) — so the batch never blocks (ADR-0002), but says so on stdout first:
    a rate-limited batch must not read as a run of ordinary misses (the silent
    flood #63 exists to stop). A genuine miss (``None`` from the inner) is an
    answer and is never retried.
    """

    def __init__(
        self,
        inner: Fingerprinter,
        min_interval: float = 1.0,
        *,
        attempts: int = 3,
        backoff: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.inner = inner
        self._min_interval = min_interval
        self._attempts = attempts
        self._backoff = backoff
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def identify(self, track: Track) -> Match | None:
        for attempt in range(self._attempts):
            self._await_slot()
            try:
                return self.inner.identify(track)
            except Exception as exc:
                if attempt + 1 == self._attempts:
                    # Degrade to a miss, never block the batch — but not silently:
                    # the Track's Review entry will read "no fingerprint match",
                    # so this line is the only trace that it was a failure.
                    print(
                        f"note: fingerprinting failed {self._attempts}x for "
                        f"{track.source_url} ({type(exc).__name__}: {exc}) — treating as a miss"
                    )
                    return None
                self._sleep(self._backoff * (2**attempt))
        return None  # unreachable (attempts >= 1); keeps the contract explicit

    def _await_slot(self) -> None:
        # The lock covers only the slot claim, so waiting threads queue for spaced
        # start times while the calls themselves run concurrently.
        with self._lock:
            wait = self._next_allowed - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._next_allowed = self._clock() + self._min_interval
