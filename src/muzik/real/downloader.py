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


def _is_bare_playlist(preflight: dict | None) -> bool:
    """yt-dlp's own verdict on whether a pre-flight ``info`` is a bare playlist.

    Read off a lightweight ``process=False`` pre-flight, which resolves the URL's
    type but pulls no Track (ADR-0004). With ``noplaylist`` set (single mode) a
    ``watch?v=…&list=…`` link resolves to its single video, so only a bare playlist
    URL classifies as ``playlist``. The verdict is yt-dlp's, never a Muzik URL
    regex — the address formats are yt-dlp's to understand.
    """
    return bool(preflight) and preflight.get("_type") == "playlist"


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
        #: Source URLs that yielded no Track because every entry was already in the
        #: download archive — a re-run with nothing new (#24). Distinct from
        #: ``skipped`` (a failure routed to Review); this is not enqueued anywhere,
        #: only reported so the CLI can say "already downloaded" instead of a bare
        #: ``0 verified, 0 queued``.
        self.archive_skips: list[str] = []
        #: Video ids already announced this batch, so the progress hook prints each
        #: Track's title once (#24).
        self._announced: set[str] = set()

    def _announce_download(self, status: dict) -> None:
        """yt-dlp progress hook: print each Track's resolved title once, so a fetch
        opens with the YouTube title before yt-dlp's own ``[download] …%`` bar."""
        if status.get("status") != "downloading":
            return
        info = status.get("info_dict") or {}
        video_id = info.get("id")
        # Guard a missing id: a lone id-less entry (None) must not poison the dedup
        # set and mute every later id-less title. Dedup only on a real id; an entry
        # without one is simply announced.
        if video_id is not None and video_id in self._announced:
            return
        if video_id is not None:
            self._announced.add(video_id)
        print(info.get("title") or video_id or "downloading…")

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
            # Chatty by default (#24): suppress yt-dlp's verbose extraction log
            # (``quiet``) but keep its real progress bar (``noprogress`` off), so a
            # large fetch shows ``[download] …%`` rather than hanging silently. The
            # hook prints the resolved title first.
            "quiet": True,
            "noprogress": False,
            "progress_hooks": [self._announce_download],
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
        self._announced.clear()  # fresh per Source, so each title announces once
        try:
            with yt_dlp.YoutubeDL(self._build_opts()) as ydl:
                # Single mode pre-flights to refuse a bare playlist *before*
                # downloading — it has no video to collapse to, so it would expand
                # fully (ADR-0004). The same pre-flight also tells an archived re-run
                # from an empty Source below, so it is captured, not thrown away.
                preflight = (
                    None
                    if self._expand_playlist
                    else ydl.extract_info(source.url, download=False, process=False)
                )
                if _is_bare_playlist(preflight):
                    # A whole-Source rejection, not a per-Track skip.
                    raise PlaylistInSingleModeError(
                        "that's a playlist; pass --playlist to download all of it"
                    )
                info = ydl.extract_info(source.url, download=True)
                tracks = self._tracks_from_info(info, source.url)
                if not tracks and self._all_archived(ydl, source.url, preflight):
                    # Every entry was already in the archive (a re-run, #8), not an
                    # empty/unplayable Source (#24). Record it so the CLI can say so
                    # rather than emitting a silent, bare 0/0 summary.
                    self.archive_skips.append(source.url)
                return tracks
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

    def _tracks_from_info(self, info: dict | None, url_fallback: str) -> list[Track]:
        """Map a yt-dlp result to Tracks. None / all-falsy entries → no Tracks:
        yt-dlp downloaded nothing (a re-run, or an unplayable Source)."""
        suffix = self._output_format.file_suffix
        if info is None:
            entries: list = []
        elif "entries" in info:
            entries = list(info["entries"] or [])
        else:
            entries = [info]
        return [
            _track_from_entry(entry, self._out_dir, suffix, url_fallback)
            for entry in entries
            if entry
        ]

    def _all_archived(
        self, ydl: "yt_dlp.YoutubeDL", url: str, preflight: dict | None
    ) -> bool:
        """True when the Source resolves to entries that are ALL already in the
        download archive — a re-run with nothing new, as opposed to an empty Source.

        Consults the archive yt-dlp already maintains (``in_download_archive``)
        rather than a second live extraction: a re-run's entries resolve in the
        pre-flight yet sit in the archive, an empty Source resolves to no entries,
        and an unplayable-but-*new* Source resolves to entries that are not archived
        — so only a genuine re-run reports here. In playlist mode the pre-flight was
        skipped above, so it is resolved now — on this rare empty path only.
        """
        if preflight is None:
            preflight = ydl.extract_info(url, download=False, process=False)
        if not preflight:
            return False
        if preflight.get("_type") == "playlist":
            entries = [entry for entry in (preflight.get("entries") or []) if entry]
        else:
            entries = [preflight]
        return bool(entries) and all(ydl.in_download_archive(entry) for entry in entries)
