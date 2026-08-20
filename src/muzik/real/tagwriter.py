"""Real TagWriter — embeds Tags into an M4A with mutagen."""

from __future__ import annotations

from pathlib import Path

from mutagen.mp4 import MP4, MP4Cover

from muzik.domain import Tags, Track

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


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
            fmt = (
                MP4Cover.FORMAT_PNG
                if tags.cover_art.startswith(_PNG_MAGIC)
                else MP4Cover.FORMAT_JPEG
            )
            audio["covr"] = [MP4Cover(tags.cover_art, imageformat=fmt)]
        audio.save()
        return track.audio_path
