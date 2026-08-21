"""Whole-box tests for ticket #7: clearing the Review queue.

Drive the engine's ``clear_review_queue`` orchestrator with fake providers and a
scripted prompter (the seam the CLI fills with stdin). Covers the three clearing
paths the ticket names — accept, manual, hint-reidentify — plus list, skip, and
the mixed pass.
"""

from pathlib import Path

from muzik.domain import Match, ReviewDecision, ReviewItem, Tags
from muzik.engine import clear_review_queue
from muzik.fakes import FakeReviewQueue, FakeTagWriter
from review_support import provisional_item, review_providers

_MATCH = Match(
    title="Envy", artist="Ogi", album="Monologues", cover_art=b"ART", confidence=0.99
)


class ScriptedPrompter:
    """Answers each item with a preset ReviewDecision, keyed by source_url."""

    def __init__(self, decisions: dict[str, ReviewDecision]) -> None:
        self._decisions = decisions

    def decide(self, item: ReviewItem) -> ReviewDecision:
        return self._decisions[item.source_url]


# --- list ----------------------------------------------------------------------


def test_the_queue_can_be_listed():
    queue = FakeReviewQueue(
        items=[provisional_item("https://youtu.be/a"), provisional_item("https://youtu.be/b")]
    )
    assert [item.source_url for item in queue.items()] == [
        "https://youtu.be/a",
        "https://youtu.be/b",
    ]


# --- accept --------------------------------------------------------------------


def test_accept_writes_the_provisional_tags_as_verified_and_dequeues():
    item = provisional_item("https://youtu.be/accept")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()

    outcomes = clear_review_queue(
        review_providers(queue, writer),
        ScriptedPrompter({item.source_url: ReviewDecision(action="accept")}),
    )

    # The provisional Tags were written, now stamped verified.
    written_tags = writer.written[0][1]
    assert written_tags.verified is True
    assert written_tags.title == "Wrong Title"  # accept keeps them as-is, just verifies
    assert written_tags.artist == "Wrong Artist"
    # Dequeued.
    assert queue.items() == []
    assert outcomes[0].cleared is True
    assert outcomes[0].result is not None
    assert outcomes[0].result.tags.verified is True


# --- manual --------------------------------------------------------------------


def test_manual_writes_user_supplied_tags_verified_and_dequeues():
    item = provisional_item("https://youtu.be/manual")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()
    mine = Tags(title="Envy", artist="Ogi", album="Monologues")

    outcomes = clear_review_queue(
        review_providers(queue, writer),
        ScriptedPrompter({item.source_url: ReviewDecision(action="manual", tags=mine)}),
    )

    written_tags = writer.written[0][1]
    assert written_tags.title == "Envy"
    assert written_tags.artist == "Ogi"
    assert written_tags.album == "Monologues"
    assert written_tags.verified is True  # user-supplied Tags are written as truth
    assert queue.items() == []
    assert outcomes[0].cleared is True


# --- hint / re-identify --------------------------------------------------------


def test_a_hint_reidentifies_from_the_fingerprint_and_dequeues():
    # The original Source title disagreed with the Match, so it was queued. A hint
    # confirms the identity; the audio re-fingerprints to the (now corroborated)
    # Match, so its Tags — cover art and all — are written verified.
    item = provisional_item("https://youtu.be/hint")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()

    outcomes = clear_review_queue(
        review_providers(queue, writer, match=_MATCH),
        ScriptedPrompter(
            {item.source_url: ReviewDecision(action="hint", hint="Ogi - Envy")}
        ),
    )

    written_tags = writer.written[0][1]
    assert written_tags.verified is True
    assert written_tags.title == "Envy"
    assert written_tags.artist == "Ogi"
    assert written_tags.album == "Monologues"
    assert written_tags.cover_art == b"ART"  # the fingerprint Match's art comes along
    assert queue.items() == []
    assert outcomes[0].cleared is True


def test_a_hint_rescues_a_fingerprint_miss():
    # The Track never fingerprinted (a miss) — the case a hint most needs to help.
    # The fingerprint still misses, so the hint itself seeds the identity, and the
    # Track is tagged from it and dequeued.
    item = ReviewItem(
        source_url="https://youtu.be/miss",
        reason="no fingerprint match",
        tags=None,
        output_path=None,
        audio_path=Path("/fake/audio.m4a"),
    )
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()

    outcomes = clear_review_queue(
        review_providers(queue, writer, match=None),  # fingerprint still misses
        ScriptedPrompter(
            {item.source_url: ReviewDecision(action="hint", hint="Ogi - Envy")}
        ),
    )

    written_tags = writer.written[0][1]
    assert written_tags.verified is True
    assert written_tags.title == "Envy"
    assert written_tags.artist == "Ogi"
    assert queue.items() == []
    assert outcomes[0].cleared is True


def test_a_blank_hint_leaves_the_item_in_the_queue():
    # A hint that carries no usable title cannot re-identify anything, so the entry
    # stays queued and nothing is written.
    item = provisional_item("https://youtu.be/blank")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()

    outcomes = clear_review_queue(
        review_providers(queue, writer, match=_MATCH),
        ScriptedPrompter({item.source_url: ReviewDecision(action="hint", hint="   ")}),
    )

    assert writer.written == []
    assert [i.source_url for i in queue.items()] == ["https://youtu.be/blank"]
    assert outcomes[0].cleared is False


# --- skip + the mixed pass -----------------------------------------------------


def test_skip_leaves_the_item_in_the_queue():
    item = provisional_item("https://youtu.be/skip")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()

    outcomes = clear_review_queue(
        review_providers(queue, writer),
        ScriptedPrompter({item.source_url: ReviewDecision(action="skip")}),
    )

    assert writer.written == []
    assert [i.source_url for i in queue.items()] == ["https://youtu.be/skip"]
    assert outcomes[0].cleared is False


def test_a_mixed_pass_dequeues_only_the_cleared_items():
    accepted = provisional_item("https://youtu.be/accept")
    skipped = provisional_item("https://youtu.be/skip")
    queue = FakeReviewQueue(items=[accepted, skipped])
    writer = FakeTagWriter()

    clear_review_queue(
        review_providers(queue, writer),
        ScriptedPrompter(
            {
                accepted.source_url: ReviewDecision(action="accept"),
                skipped.source_url: ReviewDecision(action="skip"),
            }
        ),
    )

    assert [i.source_url for i in queue.items()] == ["https://youtu.be/skip"]
    assert len(writer.written) == 1
