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
