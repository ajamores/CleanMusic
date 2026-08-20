"""Real Review queue — a JSON file the batch appends to and #7 later clears.

The queue must survive a process exit (a batch fills it; the user works through it
in a separate run), so each ``enqueue`` reads the file, appends, and writes the whole
array back atomically (temp file + rename). Rewriting the whole file per item is
O(n^2) across a batch — fine for the current single-video CLI, revisit if #8's
playlists make review counts large (JSON Lines would append in O(1)).

Cover art is deliberately not stored: the provisionally-written file already holds
it, and the queue only needs a Track's identity and the reason it needs review.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from muzik.domain import ReviewItem, Tags


class JsonReviewQueue:
    """Appends ReviewItems to a JSON array on disk; reloads them with ``items``."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def enqueue(self, item: ReviewItem) -> None:
        records = self._load()
        records.append(_to_record(item))
        self._write_atomic(records)

    def items(self) -> list[ReviewItem]:
        return [_from_record(record) for record in self._load()]

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        records = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError(f"{self._path} is not a JSON array of Review items")
        return records

    def _write_atomic(self, records: list[dict]) -> None:
        """Write the whole queue via a temp file + rename, so a crash mid-write
        can never leave a truncated file that breaks the next batch."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent, prefix=".review-queue-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(records, indent=2))
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
        "tags": None
        if tags is None
        else {
            "title": tags.title,
            "artist": tags.artist,
            "album": tags.album,
            "verified": tags.verified,
        },
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
    return ReviewItem(
        source_url=record["source_url"],
        reason=record["reason"],
        tags=tags,
        output_path=Path(output_path) if output_path is not None else None,
    )
