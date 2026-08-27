"""Real Review queue — a JSON Lines file the batch appends to and #7 later clears.

The queue must survive a process exit (a batch fills it; the user works through it
in a separate run). Playlists (#8) make review counts large, so ``enqueue`` appends
a single line — O(1) — rather than rewriting the whole file (the old JSON-array
form re-serialised every record per enqueue: O(n^2) across a batch).

Append is not atomic across a crash, so a torn final line is possible; ``items``
tolerates it (skips any unparseable record) so a half-written line never breaks the
next batch's read, and ``enqueue`` first closes off an unterminated tail with a
newline so a later append lands on its own clean line rather than fusing onto the
torn one. Only ``replace_all`` — the clear pass, run once — rewrites the whole file,
and it does so atomically (temp file + rename).

Cover art is deliberately not stored: the provisionally-written file already holds
it, and the queue only needs a Track's identity and the reason it needs review.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from muzik.domain import Match, MatchConflict, ReviewItem, Tags

logger = logging.getLogger(__name__)


class JsonReviewQueue:
    """Appends ReviewItems as JSON Lines; reloads them with ``items``."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def enqueue(self, item: ReviewItem) -> None:
        """Append one record, O(1) — no read of the body, no whole-file rewrite."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_to_record(item), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as handle:
            if self._has_unterminated_tail():
                # A prior crash left a torn, newline-less line. Close it off first
                # so this record lands cleanly on its own line instead of fusing
                # onto the torn one (which would corrupt this record too).
                handle.write("\n")
            handle.write(line + "\n")

    def _has_unterminated_tail(self) -> bool:
        """True when the file ends mid-line (no trailing newline) — an O(1) peek."""
        try:
            with self._path.open("rb") as handle:
                if handle.seek(0, os.SEEK_END) == 0:
                    return False
                handle.seek(-1, os.SEEK_END)
                return handle.read(1) != b"\n"
        except FileNotFoundError:
            return False

    def items(self) -> list[ReviewItem]:
        return [_from_record(record) for record in self._load()]

    def replace_all(self, items: list[ReviewItem]) -> None:
        """Overwrite the queue with ``items`` — the survivors of a clear pass (#7)."""
        self._write_atomic(items)

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        text = self._path.read_text(encoding="utf-8")
        records: list[dict] = []
        for index, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # A crash mid-append leaves a torn, unparseable line. Skip it and
                # keep the intact records rather than failing the whole read — a
                # single half-written entry must never block the review batch.
                logger.warning(
                    "Skipping a corrupt Review-queue record on line %d of %s",
                    index + 1,
                    self._path,
                )
        return records

    def _write_atomic(self, items: list[ReviewItem]) -> None:
        """Rewrite the whole queue via a temp file + rename, so a crash mid-write
        can never leave a truncated file that breaks the next batch's read."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent, prefix=".review-queue-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for item in items:
                    handle.write(json.dumps(_to_record(item), ensure_ascii=False) + "\n")
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _to_record(item: ReviewItem) -> dict:
    tags = item.tags
    return {
        "source_url": item.source_url,
        "reason": item.reason,
        "output_path": str(item.output_path) if item.output_path is not None else None,
        "audio_path": str(item.audio_path) if item.audio_path is not None else None,
        "tags": None
        if tags is None
        else {
            "title": tags.title,
            "artist": tags.artist,
            "album": tags.album,
            "verified": tags.verified,
        },
        "conflict": _conflict_record(item.conflict),
    }


def _conflict_record(conflict: MatchConflict | None) -> dict | None:
    """The rejected-Match conflict as a plain dict, or None (#24).

    Only what the Review output renders is kept — the heard Match's title/artist/
    confidence, the witnesses, and the ``why``. Cover art is dropped, as elsewhere
    in the queue: the provisional file already holds it.
    """
    if conflict is None:
        return None
    return {
        "heard": {
            "title": conflict.heard.title,
            "artist": conflict.heard.artist,
            "confidence": conflict.heard.confidence,
        },
        "source_artist": conflict.source_artist,
        "uploader": conflict.uploader,
        "why": conflict.why,
        "witness_rationale": conflict.witness_rationale,
    }


def _from_record(record: dict) -> ReviewItem:
    raw_tags = record.get("tags")
    tags = (
        None
        if raw_tags is None
        else Tags(
            title=raw_tags["title"],
            artist=raw_tags["artist"],
            album=raw_tags["album"],
            verified=raw_tags["verified"],
        )
    )
    output_path = record.get("output_path")
    audio_path = record.get("audio_path")
    return ReviewItem(
        source_url=record["source_url"],
        reason=record["reason"],
        tags=tags,
        output_path=Path(output_path) if output_path is not None else None,
        audio_path=Path(audio_path) if audio_path is not None else None,
        conflict=_conflict_from_record(record.get("conflict")),
    )


def _conflict_from_record(raw: dict | None) -> MatchConflict | None:
    """Rebuild a MatchConflict from its record, or None (#24)."""
    if raw is None:
        return None
    heard = raw["heard"]
    return MatchConflict(
        heard=Match(
            title=heard["title"],
            artist=heard["artist"],
            album="",
            confidence=heard["confidence"],
        ),
        source_artist=raw["source_artist"],
        uploader=raw["uploader"],
        why=raw["why"],
        # Absent on pre-#74 records: degrade to "no rationale", never a KeyError.
        witness_rationale=raw.get("witness_rationale", ""),
    )
