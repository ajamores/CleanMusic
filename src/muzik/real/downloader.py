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
    ):
        self._out_dir = Path(out_dir)
        self._cookies = cookies
        self._output_format = output_format
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
        }
        if self._cookies is not None:
            opts["cookiefile"] = str(self._cookies)
        return opts

    def download(self, source: Source) -> list[Track]:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(self._build_opts()) as ydl:
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

        suffix = self._output_format.file_suffix
        entries = info.get("entries") if "entries" in info else [info]
        return [
            _track_from_entry(entry, self._out_dir, suffix, source.url)
            for entry in entries
            if entry
        ]
