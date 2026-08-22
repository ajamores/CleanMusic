"""JSON Lines Review queue (ticket #8): O(1) append + torn-tail crash-safety.

Playlists make review counts large, so ``enqueue`` must append one line rather
than rewrite the whole file (the old JSON-array queue was O(n) per enqueue,
O(n^2) per batch). A torn append — the process dies mid-write — must not break
the next batch's read: a partial final line is tolerated, not fatal.
"""

from pathlib import Path

from muzik.domain import Match, MatchConflict, ReviewItem, Tags
from muzik.real.review_queue import JsonReviewQueue


def _item(source_url: str, reason: str = "unverified") -> ReviewItem:
    return ReviewItem(source_url=source_url, reason=reason)


def test_enqueue_appends_one_line_per_item(tmp_path):
    path = tmp_path / "review-queue.jsonl"
    queue = JsonReviewQueue(path)
    for n in range(5):
        queue.enqueue(_item(f"https://youtu.be/{n}"))

    # One JSON Lines record per enqueue — the append-only, O(1) shape.
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 5
    assert [item.source_url for item in queue.items()] == [
        f"https://youtu.be/{n}" for n in range(5)
    ]


def test_enqueue_does_not_rewrite_prior_lines(tmp_path):
    # Append, not read-modify-write: an already-written record is never rewritten,
    # so a hand-appended raw line survives a subsequent enqueue untouched.
    path = tmp_path / "review-queue.jsonl"
    queue = JsonReviewQueue(path)
    queue.enqueue(_item("https://youtu.be/one"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"source_url": "https://youtu.be/raw", "reason": "hand-written"}\n')

    queue.enqueue(_item("https://youtu.be/three"))

    assert [item.source_url for item in queue.items()] == [
        "https://youtu.be/one",
        "https://youtu.be/raw",
        "https://youtu.be/three",
    ]


def test_a_torn_final_line_is_tolerated_on_read(tmp_path):
    # A crash mid-append leaves a truncated last line. The next batch's read must
    # recover every intact record and simply drop the torn tail — not raise.
    path = tmp_path / "review-queue.jsonl"
    queue = JsonReviewQueue(path)
    queue.enqueue(_item("https://youtu.be/one"))
    queue.enqueue(_item("https://youtu.be/two"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"source_url": "https://youtu.be/tor')  # torn, no newline

    reopened = JsonReviewQueue(path).items()
    assert [item.source_url for item in reopened] == [
        "https://youtu.be/one",
        "https://youtu.be/two",
    ]


def test_enqueue_after_a_torn_tail_still_records(tmp_path):
    # And the batch goes on: enqueuing after a torn tail must not itself break.
    path = tmp_path / "review-queue.jsonl"
    queue = JsonReviewQueue(path)
    queue.enqueue(_item("https://youtu.be/one"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"source_url": "half')

    queue.enqueue(_item("https://youtu.be/two"))
    survivors = [item.source_url for item in JsonReviewQueue(path).items()]
    assert "https://youtu.be/one" in survivors
    assert "https://youtu.be/two" in survivors


def test_round_trips_full_item_fields(tmp_path):
    # The record shape (tags, paths) survives the JSONL round-trip unchanged.
    path = tmp_path / "review-queue.jsonl"
    item = ReviewItem(
        source_url="https://youtu.be/full",
        reason="unverified: provisional",
        tags=Tags(title="Envy", artist="Ogi", album="Monologues", verified=False),
        output_path=Path("/out/envy.m4a"),
        audio_path=Path("/tmp/envy.m4a"),
    )
    JsonReviewQueue(path).enqueue(item)

    got = JsonReviewQueue(path).items()[0]
    assert got.source_url == item.source_url
    assert got.reason == item.reason
    assert got.tags == item.tags
    assert got.output_path == item.output_path
    assert got.audio_path == item.audio_path


def test_round_trips_the_match_conflict(tmp_path):
    # #24: the rejected-Match conflict must survive to a later ``--review`` run, so
    # the clear pass shows the same explanation the batch did.
    path = tmp_path / "review-queue.jsonl"
    item = ReviewItem(
        source_url="https://youtu.be/c",
        reason="unverified: provisional Tags from the Source, Match not corroborated",
        tags=Tags(title="Drift Away", artist="Ab-Soul", album="", verified=False),
        conflict=MatchConflict(
            heard=Match(title="Drift Away", artist="Dobie Gray", album="", confidence=0.62),
            source_artist="Ab-Soul",
            uploader="Top Dawg Entertainment",
            why="artist didn't match, kept provisional",
        ),
    )
    JsonReviewQueue(path).enqueue(item)

    got = JsonReviewQueue(path).items()[0]
    assert got.conflict == item.conflict


def test_a_conflictless_item_round_trips_with_no_conflict(tmp_path):
    # A queue entry without a conflict (e.g. no fingerprint match) reloads as None.
    path = tmp_path / "review-queue.jsonl"
    JsonReviewQueue(path).enqueue(_item("https://youtu.be/plain"))
    assert JsonReviewQueue(path).items()[0].conflict is None


def test_replace_all_rewrites_as_jsonl_survivors(tmp_path):
    # The clear pass (#7) still rewrites the queue with its survivors — now JSONL.
    path = tmp_path / "review-queue.jsonl"
    queue = JsonReviewQueue(path)
    queue.enqueue(_item("https://youtu.be/one"))
    queue.enqueue(_item("https://youtu.be/two"))
    queue.enqueue(_item("https://youtu.be/three"))

    queue.replace_all([_item("https://youtu.be/two"), _item("https://youtu.be/three")])

    assert [item.source_url for item in JsonReviewQueue(path).items()] == [
        "https://youtu.be/two",
        "https://youtu.be/three",
    ]
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
