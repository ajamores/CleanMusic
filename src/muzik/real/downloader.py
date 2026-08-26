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


def _thumbnail_url(entry: dict) -> str:
    """The best thumbnail URL yt-dlp offers for an entry, or "" when it names none.

    yt-dlp's top-level ``thumbnail`` is the one it already selected as best; prefer
    it. When it is absent (some flat or live entries), fall back to the last of
    ``thumbnails`` — yt-dlp orders that list worst→best, so the last is the highest
    resolution. Only the URL is carried onto the Track (#37); nothing is fetched here.
    """
    top = entry.get("thumbnail")
    if top:
        return top
    thumbnails = entry.get("thumbnails") or []
    if thumbnails:
        last = thumbnails[-1]
        return last.get("url", "") if isinstance(last, dict) else ""
    return ""


def _track_from_entry(
    entry: dict, out_dir: Path, suffix: str, url_fallback: str
) -> Track:
    """Map one yt-dlp info entry to a Track.

    The uploader is the artist witness the Confidence gate leans on (#11); yt-dlp
    exposes it as ``uploader`` (the channel), falling back to ``channel``, then "".

    Description, tags, and the thumbnail URL are captured as identity evidence for
    the Resolver's forthcoming identity ruling (#37, ADR-0006) — pure capture, not
    yet consumed. Each defaults cleanly when yt-dlp omits it (a bare or live entry
    may carry none): missing or ``None`` text → "", missing tags → [].
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
        description=entry.get("description") or "",
        # Copy yt-dlp's list so the frozen Track owns its tags rather than aliasing
        # the info dict's mutable list.
        tags=list(entry.get("tags") or []),
        thumbnail_url=_thumbnail_url(entry),
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
        #: The Muzik-owned download manifest (#49): one video id per line, written
        #: by Muzik itself after each successful fetch. Owning the format (rather
        #: than piggy-backing yt-dlp's extractor-keyed archive) is what keeps re-run
        #: detection independent of yt-dlp internals — the coupling behind #28/#29.
        self._manifest_path = self._out_dir / ".muzik-manifest.txt"
        #: yt-dlp's old ``<extractor> <id>`` archive, read-only for back-compat
        #: (#49): pre-manifest fetches are recorded here. Muzik no longer lets
        #: yt-dlp write it, so its format is frozen — it only contributes ids.
        self._legacy_archive_path = self._out_dir / ".download-archive.txt"
        #: The already-fetched ids, lazy-loaded from the manifest (+ legacy archive)
        #: on first use and kept current in memory as this run records new fetches.
        self._fetched_ids: set[str] | None = None
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
        #: Video ids the match_filter skipped during the current ``download`` call.
        #: Confirmed live (#49): a filter skip suppresses only the *download* — a
        #: skipped single video's info dict is still returned in full — so entry
        #: mapping must drop these ids itself or it would emit a Track pointing at
        #: audio that was never fetched.
        self._filter_skipped: set[str] = set()
        #: The expanded playlist's own title (#25), set during ``download`` only when
        #: a ``--playlist`` run resolved a Source to a playlist. ``None`` in single
        #: mode — the engine writes no ``.m3u8`` then, there being no list to preserve.
        self.playlist_title: str | None = None

    def _skip_already_fetched(self, info: dict, *, incomplete: bool = False) -> str | None:
        """yt-dlp match_filter (#49): skip an entry whose video id the manifest
        already holds; a reason string skips, None downloads.

        Accepting ``incomplete`` opts in to being consulted on flat playlist
        entries too, so an archived entry is skipped before its page is extracted
        (the cost profile ``download_archive`` had). A flat entry with no id yet
        is let through — the complete pass decides it.
        """
        video_id = info.get("id")
        if video_id and video_id in self._fetched():
            self._filter_skipped.add(video_id)
            return f"{video_id} is already in the Muzik download manifest"
        return None

    def _record_fetched(self, filepath: str) -> None:
        """yt-dlp post hook (#49): record a fetched video id in the manifest.

        Called with the final filepath after all postprocessing — the same point
        yt-dlp's own archive recorded at — so only a fully-landed Track is
        recorded. The stem is the id (outtmpl is ``%(id)s.%(ext)s``). The id also
        joins the in-memory set, so the filter skips it for the rest of this run.

        A write failure is swallowed: the id stays recorded in memory (no
        re-download this run) and is simply re-fetched next run. An exception
        escaping a post hook becomes a yt-dlp error, so bookkeeping raising here
        would abort the very batch it must never abort (#32).
        """
        video_id = Path(filepath).stem
        if not video_id or video_id in self._fetched():
            return
        self._fetched().add(video_id)
        try:
            with self._manifest_path.open("a", encoding="utf-8") as manifest:
                manifest.write(f"{video_id}\n")
        except OSError as error:
            logger.warning("could not record %s in the download manifest: %s",
                           video_id, error)

    def _fetched(self) -> set[str]:
        """The already-fetched ids: loaded from disk once per Downloader, then kept
        current in memory as this run records fetches."""
        if self._fetched_ids is None:
            self._fetched_ids = self._archived_ids()
        return self._fetched_ids

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
            # Decided by the Muzik-owned manifest via match_filter (#49), not
            # yt-dlp's extractor-keyed ``download_archive`` (the #28/#29 coupling):
            # a reason string skips the entry, None lets it download.
            "match_filter": self._skip_already_fetched,
            # Each fully-landed Track's id is recorded in the manifest — after all
            # postprocessing, the point yt-dlp's own archive recorded at (#49).
            "post_hooks": [self._record_fetched],
        }
        if self._cookies is not None:
            opts["cookiefile"] = str(self._cookies)
        return opts

    def download(self, source: Source) -> list[Track]:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._announced.clear()  # fresh per Source, so each title announces once
        self._filter_skipped.clear()  # skips are per download call, like announcements
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
        if not tracks and self._filter_skipped:
            # Nothing was pulled and the filter skipped at least one entry: a
            # re-run with nothing new (#8), not an empty or unplayable Source
            # (#24). Record it so the CLI can say so rather than emitting a
            # silent, bare 0/0 summary. The filter's own skips are the evidence —
            # no second, archive-free resolve of the Source (#49): the old
            # resolve-and-compare depended on the same extraction internals
            # (lazy ``process=False`` generators, flat entries) this ticket
            # exists to stop leaning on, and cost a network round-trip per
            # empty result.
            self.archive_skips.append(source.url)
        return tracks

    def _tracks_from_info(self, info: dict | None, url_fallback: str) -> list[Track]:
        """Map a yt-dlp result to Tracks. None / all-falsy entries → no Tracks:
        yt-dlp downloaded nothing (a re-run, or an unplayable Source). An entry the
        match_filter skipped this call is dropped too — its info still comes back
        in full (#49), but no audio was fetched for it."""
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
            if entry and entry.get("id") not in self._filter_skipped
        ]

    def _archived_ids(self) -> set[str]:
        """The video ids already fetched: the Muzik manifest (one id per line, #49)
        unioned with the frozen legacy yt-dlp archive (``<extractor> <id>`` lines,
        #8 — the id is the last field, extractor aside).

        Either file failing to read — missing, permission denied, unexpectedly a
        directory — simply contributes nothing, degrading to "not a re-run".
        Archive bookkeeping must never abort the batch (#32).
        """
        ids: set[str] = set()
        try:
            manifest = self._manifest_path.read_text(encoding="utf-8")
            ids.update(line.strip() for line in manifest.splitlines() if line.strip())
        except OSError:
            pass
        try:
            legacy = self._legacy_archive_path.read_text(encoding="utf-8")
            ids.update(line.split()[-1] for line in legacy.splitlines() if line.strip())
        except OSError:
            pass
        return ids
