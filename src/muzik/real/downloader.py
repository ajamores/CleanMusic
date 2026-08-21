"""Real Downloader — pulls a Source's audio with yt-dlp in the chosen format.

M4A (default) prefers a native AAC stream and copies it — no re-encode. MP3 320
(fallback) re-encodes. A download that fails — an age wall without cookies, a
private/deleted video, a network error — is recorded on ``skipped`` with a reason
and the batch is not aborted (ADR-0002 / #6: a failed Source routes to the Review
queue, not to failure).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from muzik.domain import Source, Track
from muzik.providers import PlaylistInSingleModeError
from muzik.settings import DEFAULT_FORMAT, OutputFormat

logger = logging.getLogger(__name__)

# Specific phrases yt-dlp emits for an age wall. Deliberately NOT a bare "age":
# that is a substring of "webpage", so yt-dlp's generic "Unable to download
# webpage" errors would be misread as age restriction and silently swallowed.
_AGE_MARKERS = (
    "confirm your age",
    "sign in to confirm your age",
    "age-restricted",
    "age restricted",
    "inappropriate for some users",
)


def _is_age_restriction(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _AGE_MARKERS)


def _is_bare_playlist(ydl: "yt_dlp.YoutubeDL", url: str) -> bool:
    """yt-dlp's own verdict on whether ``url`` is a bare playlist (ADR-0004).

    A lightweight pre-flight: ``process=False`` resolves the URL's type but pulls
    no tracks. With ``noplaylist`` set (single mode) a ``watch?v=…&list=…`` link
    resolves to its single video, so only a bare playlist URL classifies as
    ``playlist``. The verdict is yt-dlp's, never a Muzik URL regex — the address
    formats are yt-dlp's to understand.
    """
    info = ydl.extract_info(url, download=False, process=False)
    return bool(info) and info.get("_type") == "playlist"


def _track_from_entry(
    entry: dict, out_dir: Path, suffix: str, url_fallback: str
) -> Track:
    """Map one yt-dlp info entry to a Track.

    The uploader is the artist witness the Confidence gate leans on (#11); yt-dlp
    exposes it as ``uploader`` (the channel), falling back to ``channel``, then "".
    """
    return Track(
        source_url=entry.get("webpage_url", url_fallback),
        audio_path=out_dir / f"{entry['id']}{suffix}",
        source_title=entry.get("title", ""),
        uploader=entry.get("uploader") or entry.get("channel") or "",
    )


class YtDlpDownloader:
    """Downloads bestaudio and extracts it to the chosen format, one Track per video."""

    def __init__(
        self,
        out_dir: Path,
        cookies: Path | None = None,
        output_format: OutputFormat = DEFAULT_FORMAT,
        expand_playlist: bool = False,
    ):
        self._out_dir = Path(out_dir)
        self._cookies = cookies
        self._output_format = output_format
        #: Single by default (ADR-0004): a Source names one Track, and an attached
        #: ``list=`` is dropped. ``--playlist`` sets this True for one run to expand
        #: the list; it is never persisted.
        self._expand_playlist = expand_playlist
        #: ``(title_or_url, reason)`` for every Source skipped this batch.
        self.skipped: list[tuple[str, str]] = []

    def _build_opts(self) -> dict:
        codec = self._output_format.yt_dlp_codec
        if self._output_format is OutputFormat.MP3_320:
            # Fallback: no native MP3 on YouTube, so re-encode to 320 kbps.
            fmt = "bestaudio/best"
            extract = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": "320",
            }
        else:
            # Default: prefer a native m4a/aac stream so it can be copied, not transcoded.
            fmt = "bestaudio[ext=m4a]/bestaudio/best"
            extract = {"key": "FFmpegExtractAudio", "preferredcodec": codec}

        opts: dict = {
            "format": fmt,
            "outtmpl": str(self._out_dir / "%(id)s.%(ext)s"),
            "postprocessors": [extract],
            "quiet": True,
            "noprogress": True,
            # Single by default (ADR-0004): yt-dlp drops an attached ``list=`` when
            # the URL also names a video, so no Muzik-side URL parsing. ``--playlist``
            # flips this to expand the list.
            "noplaylist": not self._expand_playlist,
            # Re-running a Source must not re-download Tracks already fetched (#8).
            # yt-dlp records each downloaded video's id here and skips any it has
            # already seen on a later run; skipped entries come back falsy and are
            # dropped in ``download``.
            "download_archive": str(self._out_dir / ".download-archive.txt"),
        }
        if self._cookies is not None:
            opts["cookiefile"] = str(self._cookies)
        return opts

    def download(self, source: Source) -> list[Track]:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(self._build_opts()) as ydl:
                if not self._expand_playlist and _is_bare_playlist(ydl, source.url):
                    # Refuse a bare playlist in single mode *before* downloading —
                    # it has no video to collapse to, so it would expand fully
                    # (ADR-0004). A whole-Source rejection, not a per-Track skip.
                    raise PlaylistInSingleModeError(
                        "that's a playlist; pass --playlist to download all of it"
                    )
                info = ydl.extract_info(source.url, download=True)
        except DownloadError as error:
            # Any download failure — age wall, private/deleted video, network —
            # routes the Source to the Review queue and lets the batch go on
            # (ADR-0002 / #6), rather than aborting it. Age restriction keeps its
            # actionable message; everything else carries yt-dlp's own error.
            if _is_age_restriction(error) and self._cookies is None:
                reason = "age-restricted Source needs --cookies to download"
            else:
                reason = f"download failed: {error}"
            logger.warning("Skipping %s: %s", source.url, reason)
            self.skipped.append((source.url, reason))
            return []

        if info is None:
            # yt-dlp returns None when it downloaded nothing — every entry was
            # already in the download archive (a re-run, #8), or the Source held
            # no playable video. Not a failure: there are simply no new Tracks.
            return []

        suffix = self._output_format.file_suffix
        entries = info.get("entries") if "entries" in info else [info]
        return [
            _track_from_entry(entry, self._out_dir, suffix, source.url)
            for entry in entries
            if entry
        ]
