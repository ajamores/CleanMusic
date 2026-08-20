"""Offline unit tests for the real Downloader's yt-dlp options (ticket #9).

No network: they assert only how options are built per output format and cookies,
covering "M4A avoids re-encoding native audio; MP3 320 is the fallback".
"""

from muzik.real.downloader import YtDlpDownloader
from muzik.settings import OutputFormat


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


def test_cookiefile_added_only_when_cookies_given(tmp_path):
    cookies = tmp_path / "cookies.txt"
    with_cookies = YtDlpDownloader(out_dir=tmp_path, cookies=cookies)._build_opts()
    without = YtDlpDownloader(out_dir=tmp_path)._build_opts()
    assert with_cookies["cookiefile"] == str(cookies)
    assert "cookiefile" not in without
