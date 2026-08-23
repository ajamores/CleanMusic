"""Offline unit tests for the real Downloader's yt-dlp options (ticket #9).

No network: they assert only how options are built per output format and cookies,
covering "M4A avoids re-encoding native audio; MP3 320 is the fallback".
"""

from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from muzik.domain import Source
from muzik.providers import PlaylistInSingleModeError
from muzik.real.downloader import YtDlpDownloader, _track_from_entry
from muzik.settings import OutputFormat


class _RaisingYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL and fails the download with a given error.

    Fails on every ``extract_info`` — the single-mode pre-flight classification as
    well as the download itself — so the error surfaces whichever call runs first.
    """

    def __init__(self, message: str):
        self._message = message

    def __call__(self, opts: dict) -> "_RaisingYoutubeDL":
        return self

    def __enter__(self) -> "_RaisingYoutubeDL":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def extract_info(self, url: str, download: bool = True, process: bool = True):
        raise DownloadError(self._message)


def _extract_audio_pp(opts: dict) -> dict:
    return next(pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegExtractAudio")


def test_m4a_copies_native_audio_without_reencoding(tmp_path):
    opts = YtDlpDownloader(out_dir=tmp_path, output_format=OutputFormat.M4A)._build_opts()
    # A native m4a/aac stream is preferred so it can be copied, not transcoded.
    assert "m4a" in opts["format"]
    pp = _extract_audio_pp(opts)
    assert pp["preferredcodec"] == "m4a"
    # No forced bitrate → yt-dlp copies rather than re-encodes.
    assert pp.get("preferredquality") in (None, "0", 0)


def test_mp3_320_is_the_reencoded_fallback(tmp_path):
    opts = YtDlpDownloader(out_dir=tmp_path, output_format=OutputFormat.MP3_320)._build_opts()
    pp = _extract_audio_pp(opts)
    assert pp["preferredcodec"] == "mp3"
    assert pp["preferredquality"] == "320"


def test_a_download_archive_in_the_out_dir_skips_already_fetched_tracks(tmp_path):
    # Re-running a Source must not re-download already-fetched Tracks (#8): yt-dlp's
    # download archive records fetched video ids and skips them next run. It lives
    # in the out dir so it persists alongside the Tracks it tracks.
    opts = YtDlpDownloader(out_dir=tmp_path)._build_opts()
    assert opts["download_archive"] == str(tmp_path / ".download-archive.txt")


def test_cookiefile_added_only_when_cookies_given(tmp_path):
    cookies = tmp_path / "cookies.txt"
    with_cookies = YtDlpDownloader(out_dir=tmp_path, cookies=cookies)._build_opts()
    without = YtDlpDownloader(out_dir=tmp_path)._build_opts()
    assert with_cookies["cookiefile"] == str(cookies)
    assert "cookiefile" not in without


def test_entry_uploader_is_carried_onto_the_track():
    # yt-dlp returns the artist most reliably as the channel `uploader`; the gate
    # (#11) uses it as the artist witness, so the Downloader must carry it.
    track = _track_from_entry(
        {"id": "abc", "title": "Ogi - Envy", "uploader": "Rick Astley",
         "channel": "Rick Astley Official"},
        out_dir=Path("/out"), suffix=".m4a", url_fallback="https://youtu.be/abc",
    )
    assert track.uploader == "Rick Astley"


def test_entry_falls_back_to_channel_then_empty():
    # No `uploader` field → fall back to `channel`; neither → "".
    from_channel = _track_from_entry(
        {"id": "x", "channel": "SomeVEVO"},
        out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    neither = _track_from_entry(
        {"id": "y"}, out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    assert from_channel.uploader == "SomeVEVO"
    assert neither.uploader == ""


def test_a_generic_download_failure_is_skipped_not_raised(tmp_path, monkeypatch):
    # A private/deleted/network failure must route the Source to the Review queue
    # (recorded on `skipped`) and let the batch go on — not abort it (#6).
    raiser = _RaisingYoutubeDL("ERROR: Private video. Sign in if you've been granted access")
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", raiser)

    downloader = YtDlpDownloader(out_dir=tmp_path)
    tracks = downloader.download(Source(url="https://youtu.be/private"))

    assert tracks == []
    assert len(downloader.skipped) == 1
    url, reason = downloader.skipped[0]
    assert url == "https://youtu.be/private"
    assert reason  # a non-empty reason for the user


class _NullInfoYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL when extract_info returns None — every entry
    was already in the download archive (a re-run), so nothing was downloaded."""

    def __call__(self, opts: dict) -> "_NullInfoYoutubeDL":
        return self

    def __enter__(self) -> "_NullInfoYoutubeDL":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def extract_info(self, url: str, download: bool = True, process: bool = True):
        return None


def test_a_fully_archived_run_yields_no_tracks_without_crashing(tmp_path, monkeypatch):
    # Re-running a Source whose videos are all in the download archive makes yt-dlp
    # return None. That must be an empty result, not a crash (#8 regression).
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", _NullInfoYoutubeDL())

    downloader = YtDlpDownloader(out_dir=tmp_path)
    tracks = downloader.download(Source(url="https://youtu.be/already-fetched"))

    assert tracks == []
    assert downloader.skipped == []  # not a failure — just nothing new to fetch


def test_progress_bar_is_on_and_a_title_hook_is_wired(tmp_path):
    # #24: a fetch must not be a silent hang. yt-dlp's real progress bar is enabled
    # (noprogress off) and a progress hook prints each Track's title first.
    opts = YtDlpDownloader(out_dir=tmp_path)._build_opts()
    assert opts["noprogress"] is False
    assert opts["progress_hooks"]  # a hook is wired to announce the title


def test_the_title_hook_announces_each_track_once(tmp_path, capsys):
    downloader = YtDlpDownloader(out_dir=tmp_path)
    status = {"status": "downloading", "info_dict": {"id": "X", "title": "Song X"}}
    downloader._announce_download(status)
    downloader._announce_download(status)  # a second progress tick for the same id
    downloader._announce_download({"status": "finished", "info_dict": {"id": "X"}})
    out = capsys.readouterr().out
    assert out.count("Song X") == 1  # announced once, not on every tick


def _write_archive(tmp_path, *video_ids: str) -> None:
    """Write a download archive in the out dir, in yt-dlp's ``<extractor> <id>``
    line format (#8) — the file the archive-skip check reads (#24)."""
    (tmp_path / ".download-archive.txt").write_text(
        "".join(f"youtube {video_id}\n" for video_id in video_ids), encoding="utf-8"
    )


class _ScriptedYoutubeDL:
    """Fake yt_dlp.YoutubeDL for the archive-skip path (#24).

    ``preflight`` is what any ``extract_info(download=False, …)`` returns — serving
    both the bare-playlist type check and the archive-free resolve in
    ``_all_archived`` (yt-dlp's URL classification: a video, or a playlist of flat
    entries). ``download_info`` is the ``download=True`` return. Which ids count as
    already-fetched is set by the on-disk archive (``_write_archive``), matching the
    real code, which matches by video id read from that file.
    """

    def __init__(self, preflight=None, download_info=None):
        self._preflight = preflight
        self._download_info = download_info

    def __call__(self, opts: dict) -> "_ScriptedYoutubeDL":
        return self

    def __enter__(self) -> "_ScriptedYoutubeDL":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def extract_info(self, url: str, download: bool = True, process: bool = True):
        return self._download_info if download else self._preflight


def test_an_all_archived_rerun_is_recorded_as_an_archive_skip(tmp_path, monkeypatch):
    # A re-run: the Source still resolves, but the download pulls nothing because its
    # id is already in the archive. That is an archive skip, not a failure and not an
    # empty Source (#24).
    _write_archive(tmp_path, "X")
    fake = _ScriptedYoutubeDL(
        preflight={"id": "X", "extractor_key": "Youtube"},  # a video → no refusal
        download_info=None,  # yt-dlp downloaded nothing (already archived)
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path)
    tracks = downloader.download(Source(url="https://youtu.be/X"))

    assert tracks == []
    assert downloader.archive_skips == ["https://youtu.be/X"]
    assert downloader.skipped == []  # not a failure


def test_archive_skip_matches_by_id_across_a_tab_extractor(tmp_path, monkeypatch):
    # A URL that carries a list= resolves the entry under the YoutubeTab extractor,
    # while the download recorded it under Youtube. Matching by id (not yt-dlp's
    # extractor-keyed archive check) still recognises the re-run (#24 regression).
    _write_archive(tmp_path, "aD9KtVc6svw")  # recorded as "youtube aD9KtVc6svw"
    fake = _ScriptedYoutubeDL(
        preflight={"id": "aD9KtVc6svw", "extractor_key": "YoutubeTab", "ie_key": "Youtube"},
        download_info=None,
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path)
    url = "https://www.youtube.com/watch?v=aD9KtVc6svw&list=LL&index=1"
    tracks = downloader.download(Source(url=url))

    assert tracks == []
    assert downloader.archive_skips == [url]


def test_an_all_archived_playlist_rerun_is_an_archive_skip(tmp_path, monkeypatch):
    # The playlist path: the archive check resolves the list on the empty path.
    # Every entry's id is archived → an archive skip.
    _write_archive(tmp_path, "a", "b")
    fake = _ScriptedYoutubeDL(
        preflight={"_type": "playlist", "entries": [{"id": "a"}, {"id": "b"}]},
        download_info={"entries": [None, None]},  # both archived → falsy
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path, expand_playlist=True)
    tracks = downloader.download(Source(url="https://youtube.com/playlist?list=PL"))

    assert tracks == []
    assert downloader.archive_skips == ["https://youtube.com/playlist?list=PL"]


def test_a_resolvable_but_unarchived_empty_source_is_not_an_archive_skip(tmp_path, monkeypatch):
    # The misclassification guard: the Source resolves but its id was never
    # downloaded (not in the archive) and still pulled nothing — a genuinely empty/
    # unplayable Source, NOT an archived re-run (#24). No archive file written.
    fake = _ScriptedYoutubeDL(
        preflight={"id": "NEW", "extractor_key": "Youtube"}, download_info=None
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path)
    tracks = downloader.download(Source(url="https://youtu.be/NEW"))

    assert tracks == []
    assert downloader.archive_skips == []
    assert downloader.skipped == []


def test_an_unresolvable_empty_source_is_not_an_archive_skip(tmp_path, monkeypatch):
    # A Source that resolves to nothing at all is empty, not a re-run — no skip.
    _write_archive(tmp_path, "something-else")  # archive non-empty, but nothing resolves
    fake = _ScriptedYoutubeDL(preflight=None, download_info=None)
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path)
    tracks = downloader.download(Source(url="https://youtu.be/gone"))

    assert tracks == []
    assert downloader.archive_skips == []
    assert downloader.skipped == []


def _raising_flat_entries():
    """A lazy resolve generator (the process=False shape) that raises partway —
    a transient network/HTTP error mid-pagination (#32)."""
    yield {"id": "a"}
    raise DownloadError("ERROR: Unable to download webpage (HTTP Error 403)")


class _MidResolveRaisingYoutubeDL:
    """The archive-free resolve returns a *lazy* entries generator that raises
    ``DownloadError`` as it is iterated — exactly what ``process=False`` does (#32).

    The download pulls nothing (a fully-archived re-run), so ``_all_archived`` runs
    and calls ``_resolve_entry_ids``; its generator blows up while being materialised,
    *outside* the download's own ``except DownloadError``.
    """

    def __call__(self, opts: dict) -> "_MidResolveRaisingYoutubeDL":
        return self

    def __enter__(self) -> "_MidResolveRaisingYoutubeDL":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def extract_info(self, url: str, download: bool = True, process: bool = True):
        if download:
            return None  # fully archived → yt-dlp pulled nothing
        return {"_type": "playlist", "entries": _raising_flat_entries()}


def test_a_mid_resolve_download_error_degrades_not_aborts(tmp_path, monkeypatch):
    # The archive-free resolve returns a lazy generator (process=False); a transient
    # error while paginating it raises DownloadError *outside* the download's own
    # catch. It must degrade to "can't confirm a re-run" — empty result, no crash —
    # never abort the batch (#32 / ADR-0002).
    _write_archive(tmp_path, "a")
    monkeypatch.setattr(
        "muzik.real.downloader.yt_dlp.YoutubeDL", _MidResolveRaisingYoutubeDL()
    )

    downloader = YtDlpDownloader(out_dir=tmp_path, expand_playlist=True)
    tracks = downloader.download(Source(url="https://youtube.com/playlist?list=PL"))

    assert tracks == []
    assert downloader.archive_skips == []  # couldn't confirm a re-run → not a skip
    assert downloader.skipped == []


def test_a_non_missing_archive_read_error_degrades_to_no_archive(tmp_path, monkeypatch):
    # The archive path is unreadable for a reason other than "missing" — here it is
    # unexpectedly a directory (IsADirectoryError, not FileNotFoundError). That must
    # degrade to "no usable archive" (so, not a confirmed re-run), never abort the
    # batch (#32).
    (tmp_path / ".download-archive.txt").mkdir()  # a directory where a file is expected
    fake = _ScriptedYoutubeDL(
        preflight={"id": "X", "extractor_key": "Youtube"}, download_info=None
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path)
    tracks = downloader.download(Source(url="https://youtu.be/X"))

    assert tracks == []
    assert downloader.archive_skips == []  # no usable archive → not a confirmed re-run
    assert downloader.skipped == []


def test_age_restriction_without_cookies_is_still_skipped(tmp_path, monkeypatch):
    # The existing friendly age-restriction path must survive the broadened catch.
    raiser = _RaisingYoutubeDL("ERROR: Sign in to confirm your age")
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", raiser)

    downloader = YtDlpDownloader(out_dir=tmp_path, cookies=None)
    tracks = downloader.download(Source(url="https://youtu.be/age"))

    assert tracks == []
    assert "cookies" in downloader.skipped[0][1].lower()


# --- single-song by default; --playlist to expand (ticket #22) -----------------


class _RecordingYoutubeDL:
    """Fake yt_dlp.YoutubeDL with a scripted pre-flight verdict and download.

    ``preflight`` is what ``extract_info(..., process=False)`` returns (yt-dlp's
    URL classification); ``download_info`` is what the real ``download=True`` call
    returns. It records whether a download was ever attempted so a test can prove a
    refused Source pulls nothing.
    """

    def __init__(self, preflight: dict | None, download_info: dict | None):
        self._preflight = preflight
        self._download_info = download_info
        self.downloaded = False

    def __call__(self, opts: dict) -> "_RecordingYoutubeDL":
        return self

    def __enter__(self) -> "_RecordingYoutubeDL":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def extract_info(self, url: str, download: bool = True, process: bool = True):
        if not download:  # the lightweight classification pre-flight
            return self._preflight
        self.downloaded = True
        return self._download_info


def test_single_mode_sets_noplaylist_true(tmp_path):
    # Default single mode: yt-dlp drops an attached list= for us — no Muzik URL parsing.
    opts = YtDlpDownloader(out_dir=tmp_path)._build_opts()
    assert opts["noplaylist"] is True


def test_playlist_mode_sets_noplaylist_false(tmp_path):
    # --playlist expands the list: noplaylist off for this run only.
    opts = YtDlpDownloader(out_dir=tmp_path, expand_playlist=True)._build_opts()
    assert opts["noplaylist"] is False


def test_a_bare_playlist_in_single_mode_is_refused_and_downloads_nothing(tmp_path, monkeypatch):
    # yt-dlp classifies a bare playlist URL as _type == "playlist"; single mode
    # refuses it before any download, rather than silently expanding (ADR-0004).
    fake = _RecordingYoutubeDL(preflight={"_type": "playlist"}, download_info={"entries": []})
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path)
    with pytest.raises(PlaylistInSingleModeError) as excinfo:
        downloader.download(Source(url="https://youtube.com/playlist?list=PL"))

    assert "--playlist" in str(excinfo.value)  # an actionable message
    assert fake.downloaded is False  # nothing was pulled
    assert downloader.skipped == []  # a refusal is not a per-Track skip


def test_a_combined_watch_and_list_url_in_single_mode_downloads_only_the_video(tmp_path, monkeypatch):
    # With noplaylist on, yt-dlp classifies a watch?v=X&list=… link as its single
    # video (not a playlist), so single mode proceeds and downloads only Track X.
    fake = _RecordingYoutubeDL(
        preflight={"_type": "url", "id": "X"},
        download_info={"id": "X", "title": "Song X", "uploader": "Chan"},
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    tracks = YtDlpDownloader(out_dir=tmp_path).download(
        Source(url="https://www.youtube.com/watch?v=X&list=RDX")
    )

    assert fake.downloaded is True
    assert [t.audio_path.stem for t in tracks] == ["X"]


def test_playlist_mode_expands_a_bare_playlist_without_refusing(tmp_path, monkeypatch):
    # Under --playlist a bare playlist is the whole point: no pre-flight refusal,
    # and every entry becomes a Track.
    fake = _RecordingYoutubeDL(
        preflight={"_type": "playlist"},  # never consulted in playlist mode
        download_info={"entries": [
            {"id": "a", "title": "A"}, {"id": "b", "title": "B"},
        ]},
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    tracks = YtDlpDownloader(out_dir=tmp_path, expand_playlist=True).download(
        Source(url="https://youtube.com/playlist?list=PL")
    )

    assert [t.audio_path.stem for t in tracks] == ["a", "b"]


# --- playlist title + duration for the .m3u8 (ticket #25) -----------------------


def test_a_playlist_expansion_captures_yt_dlps_own_title(tmp_path, monkeypatch):
    # The .m3u8 (#25) is named after the playlist's own title as yt-dlp classifies
    # it — captured on the download result, never parsed from the URL.
    fake = _RecordingYoutubeDL(
        preflight={"_type": "playlist"},
        download_info={"_type": "playlist", "title": "Aug 2026", "entries": [
            {"id": "a", "title": "A"},
        ]},
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path, expand_playlist=True)
    downloader.download(Source(url="https://youtube.com/playlist?list=PL"))

    assert downloader.playlist_title == "Aug 2026"


def test_a_titleless_expansion_still_signals_a_write(tmp_path, monkeypatch):
    # A real expansion whose yt-dlp info carries no title must still write a .m3u8
    # (the grouping is the point) — so playlist_title is "" (not None), which the
    # engine treats as "expanded" and the writer names "playlist" (#25).
    fake = _RecordingYoutubeDL(
        preflight={"_type": "playlist"},
        download_info={"_type": "playlist", "entries": [{"id": "a", "title": "A"}]},
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path, expand_playlist=True)
    downloader.download(Source(url="https://youtube.com/playlist?list=PL"))

    assert downloader.playlist_title == ""  # signals a write, not None (single mode)


def test_single_mode_leaves_the_playlist_title_unset(tmp_path, monkeypatch):
    # A single video is not a playlist: no title, so the engine writes no .m3u8.
    fake = _RecordingYoutubeDL(
        preflight={"_type": "url", "id": "X"},
        download_info={"id": "X", "title": "Song X"},
    )
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", fake)

    downloader = YtDlpDownloader(out_dir=tmp_path)
    downloader.download(Source(url="https://youtu.be/X"))

    assert downloader.playlist_title is None


def test_entry_duration_is_carried_onto_the_track_as_whole_seconds():
    # yt-dlp reports duration as float seconds; the EXTINF line wants an int (#25).
    track = _track_from_entry(
        {"id": "abc", "title": "T", "duration": 201.6},
        out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    assert track.duration == 201


def test_entry_without_a_duration_carries_none():
    track = _track_from_entry(
        {"id": "abc", "title": "T"}, out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    assert track.duration is None


# --- capture description/tags/thumbnail as identity evidence (ticket #37) --------
#
# Per ADR-0006, the Resolver is to become an identity witness reasoning over the
# *full* download. This ticket only captures that evidence onto the Track; nothing
# consumes it yet. The thumbnail is carried as its URL (cheap, no fetch) — bytes are
# pulled on demand where the multimodal Resolver call is assembled (#38).


def test_entry_description_and_tags_are_captured_onto_the_track():
    track = _track_from_entry(
        {"id": "abc", "title": "T", "description": "Official audio.",
         "tags": ["soul", "1972"]},
        out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    assert track.description == "Official audio."
    assert track.tags == ["soul", "1972"]


def test_entry_thumbnail_url_is_captured_from_the_thumbnail_field():
    # yt-dlp's top-level `thumbnail` is the one it already picked as best.
    track = _track_from_entry(
        {"id": "abc", "title": "T", "thumbnail": "https://img/best.jpg"},
        out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    assert track.thumbnail_url == "https://img/best.jpg"


def test_entry_thumbnail_falls_back_to_the_last_of_the_thumbnails_list():
    # No top-level `thumbnail` → take the last of `thumbnails` (yt-dlp orders that
    # list worst→best, so the last is the highest resolution).
    track = _track_from_entry(
        {"id": "abc", "title": "T", "thumbnails": [
            {"url": "https://img/low.jpg"}, {"url": "https://img/high.jpg"},
        ]},
        out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    assert track.thumbnail_url == "https://img/high.jpg"


def test_entry_without_evidence_fields_defaults_cleanly():
    # A bare entry (a live cover, a flat entry) may carry none of it — the fields
    # must default cleanly, never blow up on a missing key or a None value.
    track = _track_from_entry(
        {"id": "abc", "title": "T", "description": None, "tags": None,
         "thumbnails": []},
        out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    assert track.description == ""
    assert track.tags == []
    assert track.thumbnail_url == ""


def test_captured_tags_are_copied_not_aliased_to_yt_dlps_list():
    # The Track owns its tags: mutating yt-dlp's original list must not reach back
    # into the captured Track (a frozen record should not share mutable state).
    entry_tags = ["soul"]
    track = _track_from_entry(
        {"id": "abc", "title": "T", "tags": entry_tags},
        out_dir=Path("/out"), suffix=".m4a", url_fallback="u",
    )
    entry_tags.append("mutated")
    assert track.tags == ["soul"]
