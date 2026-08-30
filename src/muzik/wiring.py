"""Shared provider wiring for the engine's adapters (ADR-0001, ADR-0010).

The CLI and the web adapter are siblings over the same engine; the *real*
providers they assemble — and the rate limits, key-degradation, and format
resolution baked into that assembly — must be one decision, not two copies that
drift. Both adapters call these builders; neither adds wiring of its own.

The "no API key" notes stay plain prints: they are a wiring-time report to
whoever launched the process, the same in a terminal and in a server log.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from muzik.domain import IdentityRuling, Match, Track
from muzik.engine import Providers
from muzik.providers import Fingerprinter, Resolver
from muzik.real.acoustid import AcoustIdFingerprinter
from muzik.real.authority import RateLimitedAuthority, ShazamOwnAuthority
from muzik.real.downloader import YtDlpDownloader
from muzik.real.fingerprinter import RateLimitedFingerprinter, ShazamFingerprinter
from muzik.real.images import HttpThumbnailFetcher
from muzik.real.playlist import M3u8PlaylistWriter
from muzik.real.resolver import HaikuResolver
from muzik.real.review_queue import JsonReviewQueue
from muzik.real.tagwriter import Mp3TagWriter, Mp4TagWriter
from muzik.settings import OutputFormat, Settings, load_settings, save_settings

#: The adapters' spellings for the saved formats — the CLI's ``--format`` choices
#: and the web API's ``format`` field alike (the API contract fixes them).
FORMAT_CHOICES = {"m4a": OutputFormat.M4A, "mp3-320": OutputFormat.MP3_320}


class DisabledResolver:
    """The AI Resolver tier, switched off when no Claude key is configured.

    The key comes from the environment / gitignored .env (``load_dotenv`` in
    each adapter's entry point). Without it the last waterfall tier proposes
    nothing rather than crashing the batch on client construction — Tracks it
    would have resolved get provisional Tags and a place in the Review queue
    instead (CONTEXT.md: the batch never blocks).
    """

    def resolve(self, track: Track, match: Match | None) -> Match | None:
        return None

    def witness_identity(
        self, track: Track, match: Match, second: Match | None = None
    ) -> IdentityRuling:
        # No key, no witness: the gate keeps the Match unverified and routes it to
        # Review, exactly as an ``unsure`` verdict would (CONTEXT.md: never block).
        return IdentityRuling(verdict="unsure", rationale="AI Resolver disabled (no API key)")


def build_resolver() -> Resolver:
    """The real Haiku Resolver when a Claude key is present, else a disabled one.

    An absent key is reported once, plainly, and degrades the AI tier instead of
    failing — see ``DisabledResolver``.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "note: no ANTHROPIC_API_KEY (set it in the environment or a .env file) — "
            "the AI Resolver is disabled (album waterfall and identity witness); "
            "Tracks needing it go to review."
        )
        return DisabledResolver()
    return HaikuResolver()


#: Minimum seconds between Shazam ``recognize`` starts (#63). Calls still overlap
#: (only their starts are spaced), so at ~2s per recognize this costs a 4-worker
#: batch little wall-clock while capping the request rate at 1/s from this IP —
#: the same figure the MusicBrainz tier has run safely at. The slice run of the
#: seeding batch (#66) is where a smaller interval would be measured and argued.
_SHAZAM_MIN_INTERVAL = 1.0

#: AcoustID asks applications to stay under ~3 requests/second; it is consulted
#: only on the witness's unsure/miss paths, so this spacing is rarely even felt.
_ACOUSTID_MIN_INTERVAL = 0.35


def build_acoustid() -> Fingerprinter:
    """The second acoustic source (AcoustID, #51), reported once when disabled.

    Like the Resolver, it self-disables without a key: ``AcoustIdFingerprinter``
    identifies nothing when ``ACOUSTID_API_KEY`` is absent, so the identity witness
    simply falls back to Shazam alone. The note tells the user the second witness is
    off (and that ``fpcalc`` is also required — see docs/DEVELOPMENT.md). A keyed
    AcoustID is rate-limited like Shazam (#63); a keyless one is left bare — its
    instant ``None`` needs no spacing.
    """
    if not os.environ.get("ACOUSTID_API_KEY"):
        print(
            "note: no ACOUSTID_API_KEY (set it in the environment or a .env file) — "
            "the second acoustic witness (AcoustID) is disabled; identity checks use "
            "Shazam alone."
        )
        return AcoustIdFingerprinter()
    # For AcoustID the wrapper contributes *spacing only*: the adapter swallows
    # its own failures to a miss (see acoustid.py), so the retry path never fires.
    # Deliberate — a second opinion is optional evidence, not worth retry latency.
    return RateLimitedFingerprinter(
        AcoustIdFingerprinter(), min_interval=_ACOUSTID_MIN_INTERVAL
    )


def build_downloader(
    out_dir: Path,
    cookies: Path | None,
    fmt: OutputFormat,
    expand_playlist: bool = False,
    limit: int | None = None,
    on_event: Callable[[dict], None] | None = None,
) -> YtDlpDownloader:
    """The real Downloader. ``on_event`` is the web adapter's download-progress
    seam (per-tick dicts from the yt-dlp hook); the CLI leaves it None."""
    return YtDlpDownloader(
        out_dir=out_dir,
        cookies=cookies,
        output_format=fmt,
        expand_playlist=expand_playlist,
        playlist_limit=limit,
        on_event=on_event,
    )


def build_providers(
    downloader: YtDlpDownloader, fmt: OutputFormat, out_dir: Path
) -> Providers:
    tagwriter = Mp4TagWriter() if fmt is OutputFormat.M4A else Mp3TagWriter()
    return Providers(
        downloader=downloader,
        # Spaced and retried (#63): a ~400-Track batch must not fire hundreds of
        # rapid recognize calls from one IP, and a transient failure retries with
        # backoff instead of silently flooding the Review queue as misses.
        fingerprinter=RateLimitedFingerprinter(
            ShazamFingerprinter(), min_interval=_SHAZAM_MIN_INTERVAL
        ),
        # A playlist runs Tracks concurrently (#8), so the MusicBrainz tier is
        # spaced to ~1 req/sec — its documented rate limit (ADR-0002).
        authority=RateLimitedAuthority(ShazamOwnAuthority(), min_interval=1.0),
        resolver=build_resolver(),
        tagwriter=tagwriter,
        review_queue=JsonReviewQueue(out_dir / "review-queue.jsonl"),
        # Writes a .m3u8 only on a --playlist expansion (#25); a single-mode run
        # leaves the Downloader's playlist_title None, so the engine calls it not.
        playlist_writer=M3u8PlaylistWriter(out_dir),
        # Fallback cover art (#52): a Track left bare by identification gets its
        # video thumbnail embedded instead of shipping with no art.
        thumbnail_fetcher=HttpThumbnailFetcher(),
        # Second acoustic witness (#51): AcoustID, consulted only on the unsure/miss
        # paths (ADR-0006) — the fast path stays Shazam-only (#38).
        acoustid=build_acoustid(),
    )


def resolve_format(chosen: str | None, settings_path: Path | None = None) -> OutputFormat:
    """Persist an explicit format choice (a ``FORMAT_CHOICES`` spelling), else
    read the saved setting — the same rule for both adapters. ``settings_path``
    overrides the settings file's location (the web adapter's demo/test
    isolation); None is the user's real one."""
    if chosen is not None:
        fmt = FORMAT_CHOICES[chosen]
        save_settings(Settings(output_format=fmt), settings_path)
        return fmt
    return load_settings(settings_path).output_format
