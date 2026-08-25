"""Whole-box tests for ticket #6: persisted Review queue + batch summary.

Driven through the engine entry with fake providers (test_engine.py style), plus
a focused test that the real JsonReviewQueue survives a process exit.
"""

from pathlib import Path

from muzik.domain import Match, Source
from muzik.engine import Providers, run, summarize
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeReviewQueue,
    FakeTagWriter,
)
from muzik.real.review_queue import JsonReviewQueue

_MATCH = Match(
    title="Envy", artist="Ogi", album="Monologues", cover_art=b"ART", confidence=0.99
)


def _providers(
    match: Match | None,
    queue: FakeReviewQueue,
    *,
    source_title: str = "Fake Video",
    uploader: str = "",
    downloader: FakeDownloader | None = None,
) -> Providers:
    return Providers(
        downloader=downloader
        or FakeDownloader(title=source_title, uploader=uploader),
        fingerprinter=FakeFingerprinter(match=match),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=FakeTagWriter(),
        review_queue=queue,
    )


# --- what gets enqueued --------------------------------------------------------


def test_a_verified_track_is_not_queued():
    queue = FakeReviewQueue()
    results = run(
        Source(url="https://youtu.be/ok"),
        _providers(_MATCH, queue, source_title="Ogi - Envy (Official Video)"),
    )
    assert results[0].tags.verified is True
    assert queue.items() == []
    assert summarize(results).verified == 1
    assert summarize(results).queued == 0


def test_a_gate_failure_is_queued_with_its_provisional_tags_and_a_reason():
    # The Source names a different "Artist - Title" than the Match: the Track is
    # written provisionally and enqueued, never as verified truth.
    queue = FakeReviewQueue()
    results = run(
        Source(url="https://youtu.be/bad"),
        _providers(
            _MATCH,
            queue,
            source_title="Rick Astley - Never Gonna Give You Up",
        ),
    )
    assert results[0].tags.verified is False
    assert len(queue.items()) == 1
    item = queue.items()[0]
    assert item.source_url == "https://youtu.be/bad"
    assert item.tags is not None
    assert item.tags.artist == "Rick Astley"
    assert item.tags.title == "Never Gonna Give You Up"
    assert item.reason  # a non-empty reason
    assert summarize(results).queued == 1


def test_a_fingerprint_miss_is_queued_with_a_reason():
    queue = FakeReviewQueue()
    results = run(Source(url="https://youtu.be/miss"), _providers(None, queue))
    # Written best-effort from the Source (#52), but still queued for Review.
    assert results[0].status == "tagged"
    assert len(queue.items()) == 1
    assert queue.items()[0].tags is not None
    assert queue.items()[0].reason == "no fingerprint match"
    assert summarize(results).queued == 1


def test_a_skipped_download_is_queued_and_the_batch_still_completes():
    # An age-restricted entry with no cookies is skipped by the Downloader; the
    # clean entry still tags, and the skip lands in the Review queue with a reason.
    queue = FakeReviewQueue()
    downloader = FakeDownloader(
        cookies=None, entries=[("Ogi - Envy", False), ("Age-Gated Song", True)]
    )
    results = run(
        Source(url="https://youtu.be/list"),
        _providers(_MATCH, queue, downloader=downloader),
    )
    assert len(results) == 1  # the clean Track processed; batch not aborted
    assert results[0].tags.verified is True
    reasons = [item.reason for item in queue.items()]
    assert any("cookies" in reason.lower() for reason in reasons)
    assert summarize(results, len(downloader.skipped)).queued == 1


# --- the mixed-batch summary ---------------------------------------------------


def test_mixed_batch_summary_and_queue_contents():
    # One verified, one gate-failing, one skipped download → 1 verified, 2 queued.
    queue = FakeReviewQueue()
    downloader = FakeDownloader(
        entries=[
            ("Ogi - Envy", False),  # agrees on title + artist → verified
            ("Rick Astley - Never Gonna Give You Up", False),  # disagrees → queued
            ("Age-Gated Song", True),  # skipped, no cookies → queued
        ]
    )
    results = run(
        Source(url="https://youtu.be/mix"),
        _providers(_MATCH, queue, downloader=downloader),
    )

    summary = summarize(results, len(downloader.skipped))
    assert summary.verified == 1
    assert summary.queued == 2
    assert len(queue.items()) == 2


# --- persistence across process exit -------------------------------------------


def test_the_queue_persists_across_process_exit(tmp_path):
    path = tmp_path / "review-queue.json"
    JsonReviewQueue(path).enqueue(
        _review_item("https://youtu.be/one", "no fingerprint match")
    )
    JsonReviewQueue(path).enqueue(
        _review_item("https://youtu.be/two", "unverified")
    )

    # A fresh queue over the same file — a new process — reads both back.
    reopened = JsonReviewQueue(path).items()
    assert [item.source_url for item in reopened] == [
        "https://youtu.be/one",
        "https://youtu.be/two",
    ]
    assert [item.reason for item in reopened] == ["no fingerprint match", "unverified"]


def test_replace_all_rewrites_the_queue_with_the_survivors(tmp_path):
    # The clear pass (#7) rewrites the queue with the entries it did not clear.
    path = tmp_path / "review-queue.json"
    queue = JsonReviewQueue(path)
    queue.enqueue(_review_item("https://youtu.be/one", "reason one"))
    queue.enqueue(_review_item("https://youtu.be/two", "reason two"))

    queue.replace_all([_review_item("https://youtu.be/two", "reason two")])

    reopened = JsonReviewQueue(path).items()  # a fresh process reads the survivors
    assert [item.source_url for item in reopened] == ["https://youtu.be/two"]


def _review_item(source_url: str, reason: str):
    from muzik.domain import ReviewItem

    return ReviewItem(source_url=source_url, reason=reason)
