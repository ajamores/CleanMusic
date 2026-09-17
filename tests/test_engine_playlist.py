"""Offline end-to-end test for the .m3u8 a --playlist run writes (ticket #25).

Drives the engine with fakes for the network seams but the REAL M3U8 writer, so it
exercises download → tag → playlist-file without touching the network: expanding a
fake multi-entry playlist must write a correct .m3u8 (order, relative paths,
EXTINF), a single-mode run must write none, and a Track that produced no file must
not appear.
"""

from collections.abc import Sequence

from muzik.domain import Match, Source, Track
from muzik.engine import Providers, run
from muzik.fakes import FakeAuthority, FakeResolver, FakeTagWriter
from muzik.real.playlist import M3u8PlaylistWriter


class _PlaylistDownloader:
    """Stands in for yt-dlp expanding a playlist: canned Tracks + a playlist title.

    Each Track's file lands in ``out_dir`` (so its written path is a bare relative
    name in the list), carries a duration for ``#EXTINF``, and a corroborating
    "Artist - Title"/uploader so the gate verifies it. ``playlist_title`` is set,
    as the real Downloader sets it on an expansion — ``None`` mimics single mode.
    """

    def __init__(self, out_dir, tracks: Sequence[Track], playlist_title):
        self._out_dir = out_dir
        self._tracks = list(tracks)
        self.skipped: list[tuple[str, str]] = []
        self.playlist_title = playlist_title

    def download(self, source: Source) -> list[Track]:
        return list(self._tracks)

    def record_processed(self, track: Track) -> None:
        pass


class _PerTrackFingerprinter:
    """A Match parsed from each Track's own "Artist - Title", so tracks tag distinctly.

    A ``None`` source_title stands in for a fingerprint miss (no Match) — that Track
    produces no file and must be absent from the playlist.
    """

    def identify(self, track: Track) -> Match | None:
        if not track.source_title:
            return None
        artist, _, title = track.source_title.partition(" - ")
        return Match(title=title, artist=artist, album="Monologues", confidence=1.0)


def _track(out_dir, stem, title, duration):
    return Track(
        source_url=f"https://youtu.be/{stem}",
        audio_path=out_dir / f"{stem}.m4a",
        source_title=title,
        uploader=title.split(" - ")[0] if title else "",
        duration=duration,
    )


def _providers(downloader, tagwriter):
    return Providers(
        downloader=downloader,
        fingerprinter=_PerTrackFingerprinter(),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=tagwriter,
        playlist_writer=M3u8PlaylistWriter(downloader._out_dir),
    )


def test_a_playlist_run_writes_a_correct_m3u8(tmp_path):
    tracks = [
        _track(tmp_path, "a", "Ogi - Envy", 201),
        _track(tmp_path, "b", "Rick Astley - Together Forever", 205),
    ]
    downloader = _PlaylistDownloader(tmp_path, tracks, playlist_title="Aug 2026")
    run(Source(url="https://youtube.com/playlist?list=PL"), _providers(downloader, FakeTagWriter()))

    playlist = tmp_path / "Aug 2026.m3u8"
    assert playlist.read_text(encoding="utf-8") == (
        "#EXTM3U\n"
        "#EXTINF:201,Ogi - Envy\n"
        "a.m4a\n"
        "#EXTINF:205,Rick Astley - Together Forever\n"
        "b.m4a\n"
    )


def test_a_single_mode_run_writes_no_playlist(tmp_path):
    # No expansion → the Downloader leaves playlist_title None → no .m3u8 (no list
    # to preserve), even though a Track was tagged.
    downloader = _PlaylistDownloader(
        tmp_path, [_track(tmp_path, "a", "Ogi - Envy", 201)], playlist_title=None
    )
    run(Source(url="https://youtu.be/a"), _providers(downloader, FakeTagWriter()))
    assert list(tmp_path.glob("*.m3u8")) == []


def test_a_titleless_expansion_still_writes_under_a_fallback_name(tmp_path):
    # An expansion with no yt-dlp title (playlist_title == "") must still preserve
    # the grouping — the writer falls back to "playlist.m3u8" (#25), never nothing.
    downloader = _PlaylistDownloader(
        tmp_path, [_track(tmp_path, "a", "Ogi - Envy", 201)], playlist_title=""
    )
    run(Source(url="https://youtube.com/playlist?list=PL"), _providers(downloader, FakeTagWriter()))
    assert (tmp_path / "playlist.m3u8").exists()


def test_a_track_with_no_file_is_absent_from_the_playlist(tmp_path):
    # A fingerprint miss (no source_title → no Match) writes no file, so it must not
    # appear as a dead pointer; the two that did produce files do.
    tracks = [
        _track(tmp_path, "a", "Ogi - Envy", 201),
        _track(tmp_path, "miss", "", None),
        _track(tmp_path, "b", "Adele - Hello", 295),
    ]
    downloader = _PlaylistDownloader(tmp_path, tracks, playlist_title="Aug 2026")
    run(Source(url="https://youtube.com/playlist?list=PL"), _providers(downloader, FakeTagWriter()))

    body = (tmp_path / "Aug 2026.m3u8").read_text(encoding="utf-8")
    assert "miss.m4a" not in body
    assert "a.m4a" in body and "b.m4a" in body


def test_album_tags_are_untouched_by_the_playlist_feature(tmp_path):
    # The grouping lives only in the .m3u8: the Tags handed to the writer still carry
    # the real album, and the .m3u8 records no album of its own.
    downloader = _PlaylistDownloader(
        tmp_path, [_track(tmp_path, "a", "Ogi - Envy", 201)], playlist_title="Aug 2026"
    )
    tagwriter = FakeTagWriter()
    run(Source(url="https://youtube.com/playlist?list=PL"), _providers(downloader, tagwriter))

    _, tags = tagwriter.written[0]
    assert tags.album == "Monologues"  # the album Tag is intact
    assert "Monologues" not in (tmp_path / "Aug 2026.m3u8").read_text(encoding="utf-8")
