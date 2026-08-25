"""Shared thumbnail fetch — one bounded image GET behind two callers (#52).

The Resolver reads a Track's thumbnail as multimodal identity evidence (ADR-0006);
the tagging path embeds it as *fallback* cover art when identification leaves a
Track with no real art (#52). Both go through ``fetch_thumbnail`` so the fetch,
its timeout, and the media-type sniff live in one place rather than being copied.

Best-effort throughout (ADR-0002): every failure returns ``None`` so a caller
degrades — the Resolver reasons over text alone, the tagger ships bare — rather
than raise. A batch never blocks on a thumbnail.
"""

from __future__ import annotations

import urllib.request

#: How long to wait on a thumbnail GET before giving up. Shared by both callers,
#: so the witness's own worst case is this plus its API timeout (#38).
_THUMBNAIL_TIMEOUT_S = 8.0


def fetch_thumbnail(url: str) -> tuple[bytes, str] | None:
    """Fetch a thumbnail as ``(raw bytes, media_type)``, or ``None`` when unavailable.

    A missing URL, a timeout, an empty body, or any fetch error returns ``None``.
    Bounded by ``_THUMBNAIL_TIMEOUT_S``.
    """
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=_THUMBNAIL_TIMEOUT_S) as resp:
            raw = resp.read()
    except Exception:
        return None
    if not raw:
        return None
    return raw, _media_type(raw)


def _media_type(raw: bytes) -> str:
    """Sniff a supported image media type from magic bytes; default JPEG."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw[:3] == b"GIF":
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class HttpThumbnailFetcher:
    """The real ThumbnailFetcher (#52): one bounded HTTP GET, raw bytes to embed.

    The tag writer sniffs PNG vs JPEG from the bytes itself, so only the raw bytes
    are handed back — the media type ``fetch_thumbnail`` also returns is what the
    Resolver's multimodal call needs, not this one.
    """

    def fetch(self, url: str) -> bytes | None:
        result = fetch_thumbnail(url)
        return result[0] if result is not None else None
