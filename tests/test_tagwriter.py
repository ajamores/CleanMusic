"""Bench test: the real TagWriter writes Tags into an M4A that mutagen reads back.

The one piece of real I/O this skeleton ships. No network; needs ffmpeg (see the
`silent_m4a` fixture in conftest.py).
"""

from mutagen.mp4 import MP4

from muzik.domain import Tags, Track
from muzik.real.tagwriter import Mp4TagWriter


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
