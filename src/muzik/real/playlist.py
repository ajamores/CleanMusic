"""Real PlaylistWriter — writes an extended-M3U ``.m3u8`` for a ``--playlist`` run (#25).

When ``--playlist`` expands a Source into many Tracks, the monthly YouTube playlist
they came from is a grouping worth keeping — but a Track's album Tag is its *real*
album, so the grouping must live *beside* the Tags, never in them. This writer
records it as a plain ``.m3u8``: a UTF-8 extended-M3U list of relative paths, which
a music library imports as a real playlist. The Tags in the files are untouched.

Complete grouping across re-runs (the #25 triage call): a re-run's engine only sees
freshly-fetched Tracks — those already in the download archive (#8) don't come back.
Rather than prying Tags back out of every file on disk, the writer **merges with any
existing ``.m3u8`` of the same name**: it reads the prior run's own list (which
already holds the archived Tracks' paths and ``#EXTINF`` lines), keeps the entries
whose file still exists (so no dead pointers), and appends the newly-landed Tracks.
The merged list overwrites the file (overwrite-to-latest), so the grouping stays
complete without re-identifying anything.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from muzik.domain import PlaylistEntry

#: Characters no common filesystem accepts in a name (Windows is the strict one):
#: the reserved set plus control chars. Replaced with ``_`` so a playlist titled
#: "Chill / Focus" becomes "Chill _ Focus.m3u8" rather than a nested path.
_ILLEGAL_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: An ``#EXTINF:<seconds>,<display>`` line: the runtime (``-1`` when unknown) and
#: the "Artist - Title" text. Parsed when merging a prior run's own ``.m3u8``.
_EXTINF_RE = re.compile(r"^#EXTINF:\s*(-?\d+)\s*,(.*)$")


@dataclass(frozen=True)
class _Line:
    """One resolved playlist line: runtime, display text, and the file it points at.

    A single internal shape for both freshly-landed Tracks (built from Tags) and
    entries parsed back out of a prior run's ``.m3u8`` (which carry only the display
    text, not split Artist/Title) — so the merge treats them alike.
    """

    duration: int | None
    display: str
    #: Absolute path to the audio file, used to test existence and to re-derive the
    #: relative path written into the list.
    path: Path


def _sanitize(title: str) -> str:
    """A filesystem-safe basename for the playlist file, from yt-dlp's title.

    Trailing dots and spaces are stripped too (Windows rejects them). An empty or
    all-illegal title falls back to ``playlist`` so a file is still written.
    """
    cleaned = _ILLEGAL_NAME_CHARS.sub("_", title).strip().rstrip(". ")
    return cleaned or "playlist"


def _display(artist: str, title: str) -> str:
    """The ``#EXTINF`` display half: "Artist - Title", or just the title if no artist."""
    return f"{artist} - {title}" if artist else title


class M3u8PlaylistWriter:
    """Writes (and merges into) one ``.m3u8`` per playlist title in ``out_dir``."""

    def __init__(self, out_dir: Path):
        self._out_dir = Path(out_dir)
        #: The file written by the most recent ``write`` (``None`` if it wrote none),
        #: so the CLI can report where the playlist landed without re-deriving the name.
        self.last_written: Path | None = None

    def write(self, title: str, entries: list[PlaylistEntry]) -> Path | None:
        self.last_written = None
        target = self._out_dir / f"{_sanitize(title)}.m3u8"
        # Prior run's own list first (validated), then this run's new Tracks appended
        # — merged so the grouping stays complete across archived re-runs (#25).
        merged = self._merge(self._read_existing(target, exclude=target), entries)
        if not merged:
            return None  # nothing landed and no prior list to preserve — write nothing
        self._out_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(self._render(merged), encoding="utf-8")
        self.last_written = target
        return target

    def _merge(self, existing: list[_Line], entries: list[PlaylistEntry]) -> list[_Line]:
        """Prior entries (already validated), then newly-landed Tracks not already listed.

        De-duplicated by relative path: a re-run never re-downloads an archived Track,
        so a new Track should not collide with a prior line, but if one does the prior
        line wins (its position and display are kept).
        """
        new = [_Line(e.duration, _display(e.artist, e.title), e.path) for e in entries]
        merged: list[_Line] = []
        seen: set[str] = set()
        for line in [*existing, *new]:
            key = self._relative(line.path)
            if key in seen:
                continue
            seen.add(key)
            merged.append(line)
        return merged

    def _read_existing(self, target: Path, exclude: Path) -> list[_Line]:
        """Parse a prior run's ``.m3u8``, keeping only entries whose file still exists.

        Dropping vanished files keeps the guarantee of no dead pointers across re-runs.
        A missing or unreadable file yields no prior entries — the run just writes
        this batch's Tracks.
        """
        try:
            text = target.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return []
        lines: list[_Line] = []
        pending: tuple[int | None, str] | None = None
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            match = _EXTINF_RE.match(stripped)
            if match is not None:
                seconds = int(match.group(1))
                pending = (None if seconds < 0 else seconds, match.group(2).strip())
                continue
            if stripped.startswith("#"):
                continue  # some other directive (e.g. #EXTM3U) — not an entry
            # Join under out_dir unresolved, so the existence check, the self-exclude
            # comparison, and the dedup key (via _relative) all measure paths the same
            # way new entries are — no resolved-vs-unresolved mismatch under a
            # symlinked output folder.
            path = self._out_dir / stripped
            if path.exists() and path != exclude:
                duration, display = pending if pending is not None else (None, stripped)
                lines.append(_Line(duration, display, path))
            pending = None
        return lines

    def _render(self, lines: list[_Line]) -> str:
        """The full extended-M3U text: the header, then an ``#EXTINF`` + path per line."""
        out = ["#EXTM3U"]
        for line in lines:
            seconds = -1 if line.duration is None else line.duration
            out.append(f"#EXTINF:{seconds},{line.display}")
            out.append(self._relative(line.path))
        return "\n".join(out) + "\n"

    def _relative(self, path: Path) -> str:
        """``path`` relative to the playlist's own folder, in forward slashes.

        Relative so moving the folder doesn't break the list; forward slashes so the
        list is portable across platforms, as ``.m3u8`` convention expects.
        """
        return Path(os.path.relpath(path, start=self._out_dir)).as_posix()
