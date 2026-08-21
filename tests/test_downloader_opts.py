"""Offline unit tests for the real Downloader's yt-dlp options (ticket #9).

No network: they assert only how options are built per output format and cookies,
covering "M4A avoids re-encoding native audio; MP3 320 is the fallback".
"""

from pathlib import Path

from yt_dlp.utils import DownloadError

from muzik.domain import Source
from muzik.real.downloader import YtDlpDownloader, _track_from_entry
from muzik.settings import OutputFormat


class _RaisingYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL and fails the download with a given error."""

    def __init__(self, message: str):
        self._message = message

    def __call__(self, opts: dict) -> "_RaisingYoutubeDL":
        return self

    def __enter__(self) -> "_RaisingYoutubeDL":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def extract_info(self, url: str, download: bool):
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

    def extract_info(self, url: str, download: bool):
        return None


def test_a_fully_archived_run_yields_no_tracks_without_crashing(tmp_path, monkeypatch):
    # Re-running a Source whose videos are all in the download archive makes yt-dlp
    # return None. That must be an empty result, not a crash (#8 regression).
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", _NullInfoYoutubeDL())

    downloader = YtDlpDownloader(out_dir=tmp_path)
    tracks = downloader.download(Source(url="https://youtu.be/already-fetched"))

    assert tracks == []
    assert downloader.skipped == []  # not a failure — just nothing new to fetch


def test_age_restriction_without_cookies_is_still_skipped(tmp_path, monkeypatch):
    # The existing friendly age-restriction path must survive the broadened catch.
    raiser = _RaisingYoutubeDL("ERROR: Sign in to confirm your age")
    monkeypatch.setattr("muzik.real.downloader.yt_dlp.YoutubeDL", raiser)

    downloader = YtDlpDownloader(out_dir=tmp_path, cookies=None)
    tracks = downloader.download(Source(url="https://youtu.be/age"))

    assert tracks == []
    assert "cookies" in downloader.skipped[0][1].lower()
