"""Real TagWriter — embeds Tags into a Track's file.

Two writers, one per output format: M4A tags via mutagen's MP4 atoms, MP3 320
tags via ID3 frames. The CLI picks the right one from the saved setting.
"""

from __future__ import annotations

from pathlib import Path

from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TRCK, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

from muzik.domain import Tags, Track

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _is_png(cover_art: bytes) -> bool:
    return cover_art.startswith(_PNG_MAGIC)


class Mp4TagWriter:
    """Writes title/artist/album/year and embedded cover art into the M4A in place."""

    def write(self, track: Track, tags: Tags) -> Path:
        audio = MP4(str(track.audio_path))
        audio["\xa9nam"] = [tags.title]
        audio["\xa9ART"] = [tags.artist]
        audio["\xa9alb"] = [tags.album]
        if tags.track_number is not None:
            audio["trkn"] = [(tags.track_number, 0)]
        if tags.year is not None:
            audio["\xa9day"] = [str(tags.year)]
        if tags.cover_art is not None:
            fmt = MP4Cover.FORMAT_PNG if _is_png(tags.cover_art) else MP4Cover.FORMAT_JPEG
            audio["covr"] = [MP4Cover(tags.cover_art, imageformat=fmt)]
        audio.save()
        return track.audio_path


class Mp3TagWriter:
    """Writes the same Tags into an MP3 as ID3v2 frames, in place."""

    def write(self, track: Track, tags: Tags) -> Path:
        try:
            audio = ID3(str(track.audio_path))
        except ID3NoHeaderError:
            audio = ID3()
        audio["TIT2"] = TIT2(encoding=3, text=[tags.title])
        audio["TPE1"] = TPE1(encoding=3, text=[tags.artist])
        audio["TALB"] = TALB(encoding=3, text=[tags.album])
        if tags.track_number is not None:
            audio["TRCK"] = TRCK(encoding=3, text=[str(tags.track_number)])
        if tags.year is not None:
            audio["TDRC"] = TDRC(encoding=3, text=[str(tags.year)])
        if tags.cover_art is not None:
            mime = "image/png" if _is_png(tags.cover_art) else "image/jpeg"
            audio["APIC"] = APIC(
                encoding=3, mime=mime, type=3, desc="Cover", data=tags.cover_art
            )
        audio.save(str(track.audio_path))
        return track.audio_path
