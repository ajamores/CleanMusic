"""Offline tests for the M3U8 PlaylistWriter (ticket #25).

No network and no yt-dlp: they drive the writer with ``PlaylistEntry`` values and
real files in a tmp dir, covering the extended-M3U format, relative paths, the
sanitized name, and the merge-with-prior-run behaviour that keeps the grouping
complete across archived re-runs.
"""

from pathlib import Path

from muzik.domain import PlaylistEntry
from muzik.real.playlist import M3u8PlaylistWriter


def _touch(path: Path) -> Path:
    """Create an empty file (its content is irrelevant — only that it exists)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _entry(out_dir: Path, name: str, artist: str, title: str, duration=None) -> PlaylistEntry:
    return PlaylistEntry(
        duration=duration, artist=artist, title=title, path=_touch(out_dir / name)
    )


def test_writes_valid_extended_m3u_in_order(tmp_path):
    entries = [
        _entry(tmp_path, "a.m4a", "Ogi", "Envy", duration=201),
        _entry(tmp_path, "b.m4a", "Rick Astley", "Together Forever", duration=205),
    ]
    path = M3u8PlaylistWriter(tmp_path).write("Aug 2026", entries)

    assert path == tmp_path / "Aug 2026.m3u8"
    assert path.read_text(encoding="utf-8") == (
        "#EXTM3U\n"
        "#EXTINF:201,Ogi - Envy\n"
        "a.m4a\n"
        "#EXTINF:205,Rick Astley - Together Forever\n"
        "b.m4a\n"
    )


def test_paths_are_relative_to_the_playlist_folder(tmp_path):
    # The file path in the list is relative to the .m3u8's own folder, so moving the
    # folder doesn't break it — a bare filename here, never an absolute path.
    entries = [_entry(tmp_path, "song.m4a", "A", "B", duration=10)]
    path = M3u8PlaylistWriter(tmp_path).write("List", entries)
    body = path.read_text(encoding="utf-8")
    assert "song.m4a" in body
    assert str(tmp_path) not in body  # no absolute path leaked in


def test_unknown_duration_is_minus_one(tmp_path):
    entries = [_entry(tmp_path, "x.m4a", "A", "B", duration=None)]
    path = M3u8PlaylistWriter(tmp_path).write("List", entries)
    assert "#EXTINF:-1,A - B" in path.read_text(encoding="utf-8")


def test_no_artist_shows_only_the_title(tmp_path):
    entries = [_entry(tmp_path, "x.m4a", "", "Just A Title", duration=5)]
    path = M3u8PlaylistWriter(tmp_path).write("List", entries)
    assert "#EXTINF:5,Just A Title\n" in path.read_text(encoding="utf-8")


def test_title_is_filesystem_sanitized(tmp_path):
    # Illegal path chars in the playlist title become underscores rather than
    # nesting a folder or failing the write.
    entries = [_entry(tmp_path, "x.m4a", "A", "B", duration=1)]
    path = M3u8PlaylistWriter(tmp_path).write("Chill / Focus: 2026?", entries)
    assert path.name == "Chill _ Focus_ 2026_.m3u8"


def test_no_entries_and_no_prior_file_writes_nothing(tmp_path):
    writer = M3u8PlaylistWriter(tmp_path)
    assert writer.write("Empty", []) is None
    assert writer.last_written is None
    assert list(tmp_path.glob("*.m3u8")) == []


def test_last_written_records_the_written_file(tmp_path):
    writer = M3u8PlaylistWriter(tmp_path)
    entries = [_entry(tmp_path, "x.m4a", "A", "B", duration=1)]
    path = writer.write("List", entries)
    assert writer.last_written == path


def test_a_rerun_merges_new_tracks_into_the_prior_list(tmp_path):
    # First run lands two Tracks; the second run (an appended playlist) lands one
    # more, while the first two are already in the archive and don't come back.
    # The regenerated list must stay complete: prior two, then the new one (#25).
    writer = M3u8PlaylistWriter(tmp_path)
    writer.write(
        "Aug 2026",
        [
            _entry(tmp_path, "a.m4a", "Ogi", "Envy", duration=201),
            _entry(tmp_path, "b.m4a", "Rick Astley", "Together Forever", duration=205),
        ],
    )

    path = writer.write("Aug 2026", [_entry(tmp_path, "c.m4a", "Adele", "Hello", duration=295)])

    assert path.read_text(encoding="utf-8") == (
        "#EXTM3U\n"
        "#EXTINF:201,Ogi - Envy\n"
        "a.m4a\n"
        "#EXTINF:205,Rick Astley - Together Forever\n"
        "b.m4a\n"
        "#EXTINF:295,Adele - Hello\n"
        "c.m4a\n"
    )


def test_a_rerun_drops_prior_entries_whose_file_vanished(tmp_path):
    # If a prior Track's file was removed from disk, its line must not survive the
    # re-run — a playlist should never point at a file that isn't there.
    writer = M3u8PlaylistWriter(tmp_path)
    gone = _entry(tmp_path, "gone.m4a", "Old", "Song", duration=100)
    writer.write("Aug 2026", [gone])
    gone.path.unlink()  # the file disappears before the next run

    path = writer.write("Aug 2026", [_entry(tmp_path, "new.m4a", "New", "Song", duration=120)])

    body = path.read_text(encoding="utf-8")
    assert "gone.m4a" not in body
    assert "new.m4a" in body


def test_a_rerun_overwrites_the_same_file_not_a_versioned_copy(tmp_path):
    # Overwrite-to-latest: the same title writes back to the same .m3u8, never a
    # "List (2).m3u8".
    writer = M3u8PlaylistWriter(tmp_path)
    writer.write("List", [_entry(tmp_path, "a.m4a", "A", "B", duration=1)])
    writer.write("List", [_entry(tmp_path, "c.m4a", "C", "D", duration=2)])
    assert sorted(p.name for p in tmp_path.glob("*.m3u8")) == ["List.m3u8"]


def test_a_new_track_already_in_the_prior_list_is_not_duplicated(tmp_path):
    # De-dup by path: re-listing a Track already present keeps a single line for it.
    writer = M3u8PlaylistWriter(tmp_path)
    same = _entry(tmp_path, "a.m4a", "A", "B", duration=1)
    writer.write("List", [same])
    path = writer.write("List", [same])
    assert path.read_text(encoding="utf-8").count("a.m4a") == 1
