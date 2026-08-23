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
    duration = entry.get("duration")
    return Track(
        source_url=entry.get("webpage_url", url_fallback),
        audio_path=out_dir / f"{entry['id']}{suffix}",
        source_title=entry.get("title", ""),
        uploader=entry.get("uploader") or entry.get("channel") or "",
        # yt-dlp reports duration as float seconds; the .m3u8 EXTINF (#25) wants a
        # whole number. None when the entry carries no duration.
        duration=int(duration) if duration is not None else None,
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
        #: The download archive yt-dlp records fetched ids in (#8). Kept as an
        #: attribute so the archive-skip check (#24) can consult the same file.
        self._archive_path = self._out_dir / ".download-archive.txt"
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
        #: The expanded playlist's own title (#25), set during ``download`` only when
        #: a ``--playlist`` run resolved a Source to a playlist. ``None`` in single
        #: mode — the engine writes no ``.m3u8`` then, there being no list to preserve.
        self.playlist_title: str | None = None

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
            "download_archive": str(self._archive_path),
        }
        if self._cookies is not None:
            opts["cookiefile"] = str(self._cookies)
        return opts

    def download(self, source: Source) -> list[Track]:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._announced.clear()  # fresh per Source, so each title announces once
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
                if self._expand_playlist and info and info.get("_type") == "playlist":
                    # yt-dlp's own classification names the playlist (#25) — the same
                    # principle as the bare-playlist check: the title is yt-dlp's to
                    # give, never a Muzik URL regex. Set (to "" if yt-dlp names none)
                    # on a real expansion, so the grouping is always written — the
                    # writer falls back to "playlist" for an empty title. Single mode
                    # leaves it None, so nothing is written there.
                    self.playlist_title = info.get("title") or ""
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

        tracks = self._tracks_from_info(info, source.url)
        if not tracks and self._all_archived(source.url):
            # Every entry was already in the archive (a re-run, #8), not an empty or
            # unplayable Source (#24). Record it so the CLI can say so rather than
            # emitting a silent, bare 0/0 summary.
            self.archive_skips.append(source.url)
        return tracks

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

    def _all_archived(self, url: str) -> bool:
        """True when the Source resolves to video ids that are ALL already in the
        download archive — a re-run with nothing new, as opposed to an empty Source.

        Only reached when a download pulled nothing. Resolve the Source's ids first,
        then match them against the archive the batch maintains. An empty Source
        resolves to no ids; an unplayable-but-*new* Source to ids that are not in the
        archive — so only a genuine re-run reports here.

        Matching is by **video id**, not yt-dlp's own ``in_download_archive``: a URL
        that carries a ``list=`` classifies the entry under the ``YoutubeTab``
        extractor, while the download recorded it under ``Youtube`` — so the two
        archive keys disagree and the API check misses. The video id is the same
        either way, and it is what "already fetched" really means.
        """
        ids = self._resolve_entry_ids(url)
        if not ids:
            return False
        archived = self._archived_ids()
        return all(video_id in archived for video_id in ids)

    def _resolve_entry_ids(self, url: str) -> list[str]:
        """The Source's video ids, resolved *archive-free* so an already-fetched
        entry still appears (a ``download_archive`` in the opts makes yt-dlp filter
        it out during extraction, returning ``None``). Flat, so a playlist isn't
        re-extracted in full. Empty on a Source that no longer resolves."""
        opts: dict = {
            "quiet": True,
            "extract_flat": "in_playlist",
            "noplaylist": not self._expand_playlist,
        }
        if self._cookies is not None:
            opts["cookiefile"] = str(self._cookies)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
                if not info:
                    return []
                # With process=False, info["entries"] is a LAZY generator: the real
                # page-by-page extraction runs as it is iterated, so materialise the
                # ids *inside* the try. A DownloadError mid-pagination (a transient
                # network/HTTP error, a page that 403s) then degrades to "not a re-run"
                # here, rather than escaping to abort the batch (#32 / ADR-0002).
                entries = info["entries"] if "entries" in info else [info]
                return [entry["id"] for entry in entries if entry and entry.get("id")]
        except DownloadError:
            return []  # the Source no longer resolves — treat as empty, not a re-run

    def _archived_ids(self) -> set[str]:
        """The video ids already in the download archive. Its lines are
        ``<extractor> <id>`` (#8); the id is the last field, extractor aside."""
        try:
            text = self._archive_path.read_text(encoding="utf-8")
        except OSError:
            # Any read failure — the file is missing, permission denied, or the path
            # is unexpectedly a directory — means no usable archive, so degrade to
            # "not a re-run". Archive bookkeeping must never abort the batch (#32).
            return set()
        return {line.split()[-1] for line in text.splitlines() if line.strip()}
