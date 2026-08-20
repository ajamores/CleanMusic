"""Bench test: the real TagWriter writes Tags into an M4A that mutagen reads back.

The one piece of real I/O this skeleton ships. No network; needs ffmpeg (see the
`silent_m4a` fixture in conftest.py).
"""

from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from muzik.domain import Tags, Track
from muzik.real.tagwriter import Mp3TagWriter, Mp4TagWriter


def test_tags_and_cover_art_round_trip(silent_m4a, png_1px):
    tags = Tags(title="Envy", artist="Ogi", album="Monologues", cover_art=png_1px, year=2023)
    track = Track(source_url="https://youtu.be/abc", audio_path=silent_m4a)

    out = Mp4TagWriter().write(track, tags)

    reloaded = MP4(str(out))
    assert reloaded["\xa9nam"] == ["Envy"]
    assert reloaded["\xa9ART"] == ["Ogi"]
    assert reloaded["\xa9alb"] == ["Monologues"]
    assert reloaded["\xa9day"] == ["2023"]
    assert bytes(reloaded["covr"][0]) == png_1px


def test_mp3_tags_and_cover_art_round_trip(silent_mp3, png_1px):
    tags = Tags(
        title="Envy",
        artist="Ogi",
        album="Monologues",
        cover_art=png_1px,
        year=2023,
        track_number=3,
    )
    track = Track(source_url="https://youtu.be/abc", audio_path=silent_mp3)

    out = Mp3TagWriter().write(track, tags)

    reloaded = ID3(str(out))
    assert reloaded["TIT2"].text == ["Envy"]
    assert reloaded["TPE1"].text == ["Ogi"]
    assert reloaded["TALB"].text == ["Monologues"]
    assert str(reloaded["TDRC"].text[0]) == "2023"
    assert reloaded["TRCK"].text == ["3"]
    assert reloaded.getall("APIC")[0].data == png_1px
