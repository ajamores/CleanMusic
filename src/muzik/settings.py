"""The saved output-format setting (ticket #9).

The format Muzik writes a Track in is *configuration*, not domain vocabulary, so
it lives here rather than in ``domain.py``. It is persisted to a small JSON file
and read back before a batch. M4A is the default and avoids re-encoding native
audio; MP3 320 is the fallback.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class OutputFormat(str, Enum):
    """The format a Track's audio is extracted to and tagged as."""

    #: Default. Native AAC is copied, not re-encoded.
    M4A = "m4a"
    #: Fallback. Re-encoded to 320 kbps MP3.
    MP3_320 = "mp3_320"

    @property
    def file_suffix(self) -> str:
        return ".m4a" if self is OutputFormat.M4A else ".mp3"

    @property
    def yt_dlp_codec(self) -> str:
        """The ``preferredcodec`` yt-dlp's FFmpegExtractAudio should target."""
        return "m4a" if self is OutputFormat.M4A else "mp3"


DEFAULT_FORMAT = OutputFormat.M4A


@dataclass(frozen=True)
class Settings:
    """User settings that persist across batches."""

    output_format: OutputFormat = DEFAULT_FORMAT


def default_settings_path() -> Path:
    """Where the settings file lives (honours ``XDG_CONFIG_HOME``)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "muzik" / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    """Read the saved Settings, falling back to defaults if absent or unreadable."""
    path = path or default_settings_path()
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text())
        return Settings(output_format=OutputFormat(data["output_format"]))
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Persist Settings to disk, creating the parent directory as needed."""
    path = path or default_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"output_format": settings.output_format.value}, indent=2))
