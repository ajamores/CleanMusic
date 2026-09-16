"""JSON wire shapes for the web adapter (API CONTRACT v1).

Field names are fixed by the contract the UI is built against — change them there
first, or not at all. ``cover_art`` bytes are never inlined in JSON: the review
cover endpoint serves them, so a queue listing stays small.
"""

from __future__ import annotations

from muzik.domain import MatchConflict, ReviewItem, Tags, TrackResult


def tags_json(tags: Tags | None) -> dict | None:
    if tags is None:
        return None
    return {
        "title": tags.title,
        "artist": tags.artist,
        "album": tags.album,
        "track_number": tags.track_number,
        "year": tags.year,
        "verified": tags.verified,
    }


def conflict_json(conflict: MatchConflict | None) -> dict | None:
    if conflict is None:
        return None
    return {
        "heard": {
            "title": conflict.heard.title,
            "artist": conflict.heard.artist,
            # "" for a conflict reloaded from the queue file, which drops the
            # album (review_queue.py keeps only what its output renders).
            "album": conflict.heard.album,
        },
        "source_artist": conflict.source_artist,
        "uploader": conflict.uploader,
        "why": conflict.why,
        "witness_rationale": conflict.witness_rationale,
    }


def track_result_json(result: TrackResult) -> dict:
    return {
        "source_url": result.source_url,
        "status": result.status,
        "reason": result.reason,
        "output_path": str(result.output_path) if result.output_path is not None else None,
        "tags": tags_json(result.tags),
        "conflict": conflict_json(result.conflict),
    }


def review_item_json(index: int, item: ReviewItem, *, has_cover: bool | None = None) -> dict:
    """One queue entry, with its position — the handle the decision endpoint takes,
    guarded against staleness by ``source_url`` (see the decision route).

    ``has_cover`` lets the listing route pass the real answer in: the persisted
    queue deliberately drops ``cover_art`` (review_queue.py — the written file
    holds it), so in-memory Tags alone would report false for every real entry.
    None falls back to the in-memory check (demo and tests carry the bytes).
    """
    return {
        "index": index,
        "source_url": item.source_url,
        "reason": item.reason,
        "tags": tags_json(item.tags),
        "output_path": str(item.output_path) if item.output_path is not None else None,
        "conflict": conflict_json(item.conflict),
        "has_audio": item.audio_path is not None,
        "has_cover": (
            item.tags is not None and item.tags.cover_art is not None
            if has_cover is None
            else has_cover
        ),
    }
