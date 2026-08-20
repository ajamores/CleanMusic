"""Real Downloader — pulls a Source's audio as M4A with yt-dlp."""

from __future__ import annotations

from pathlib import Path

import yt_dlp

from muzik.domain import Source, Track


class YtDlpDownloader:
    """Downloads bestaudio and extracts it to M4A, one Track per video."""

    def __init__(self, out_dir: Path, cookies: Path | None = None):
        self._out_dir = Path(out_dir)
        self._cookies = cookies

    def download(self, source: Source) -> list[Track]:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": str(self._out_dir / "%(id)s.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
            "quiet": True,
            "noprogress": True,
        }
        if self._cookies is not None:
            opts["cookiefile"] = str(self._cookies)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source.url, download=True)

        entries = info.get("entries") if "entries" in info else [info]
        tracks: list[Track] = []
        for entry in entries:
            if not entry:
                continue
            tracks.append(
                Track(
                    source_url=entry.get("webpage_url", source.url),
                    audio_path=self._out_dir / f"{entry['id']}.m4a",
                    source_title=entry.get("title", ""),
                )
            )
        return tracks
