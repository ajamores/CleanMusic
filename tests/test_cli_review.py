"""The CLI's --review flow wires stdin to the engine's clear pass (#7).

Exercises _run_review over a preloaded fake queue, scripting the interactive
prompts through a stubbed ``input``.
"""

import muzik.cli as cli
from muzik.domain import Match, MatchConflict, ReviewItem, Tags
from muzik.fakes import FakeReviewQueue, FakeTagWriter
from review_support import provisional_item, review_providers


def _scripted_input(answers):
    it = iter(answers)

    def _input(prompt=""):
        return next(it)

    return _input


def test_empty_queue_reports_and_clears_nothing(capsys):
    queue = FakeReviewQueue()
    code = cli._run_review(review_providers(queue, FakeTagWriter()))
    assert code == 0
    assert "empty" in capsys.readouterr().out.lower()


def test_accept_at_the_prompt_verifies_and_dequeues(monkeypatch, capsys):
    item = provisional_item("https://youtu.be/x")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()
    monkeypatch.setattr("builtins.input", _scripted_input(["a"]))

    cli._run_review(review_providers(queue, writer))

    assert writer.written[0][1].verified is True
    assert queue.items() == []
    assert "1 cleared" in capsys.readouterr().out


def test_manual_at_the_prompt_writes_typed_tags(monkeypatch):
    item = provisional_item("https://youtu.be/m")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()
    # choice, then title / artist / album.
    monkeypatch.setattr(
        "builtins.input", _scripted_input(["m", "Envy", "Ogi", "Monologues"])
    )

    cli._run_review(review_providers(queue, writer))

    tags = writer.written[0][1]
    assert (tags.artist, tags.title, tags.album) == ("Ogi", "Envy", "Monologues")
    assert tags.verified is True
    assert queue.items() == []


def test_hint_at_the_prompt_reidentifies(monkeypatch):
    item = provisional_item("https://youtu.be/h")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()
    match = Match(title="Envy", artist="Ogi", album="Monologues", confidence=0.99)
    # choice, then the corrected "Artist - Title".
    monkeypatch.setattr("builtins.input", _scripted_input(["h", "Ogi - Envy"]))

    cli._run_review(review_providers(queue, writer, match=match))

    assert writer.written[0][1].verified is True
    assert queue.items() == []


def test_review_listing_shows_the_conflict_for_a_queued_entry(monkeypatch, capsys):
    # #24: the same rejected-Match conflict the batch showed must appear in the
    # ``--review`` listing, so a later clear pass can tell a wrongly-rejected Match
    # from a correctly-caught one.
    item = ReviewItem(
        source_url="https://youtu.be/x",
        reason="unverified: provisional Tags from the Source, Match not corroborated",
        tags=Tags(title="Drift Away", artist="Ab-Soul", album="", verified=False),
        conflict=MatchConflict(
            heard=Match(title="Drift Away", artist="Dobie Gray", album="", confidence=0.62),
            source_artist="Ab-Soul",
            uploader="Top Dawg Entertainment",
            why="artist didn't match, kept provisional",
        ),
    )
    queue = FakeReviewQueue(items=[item])
    monkeypatch.setattr("builtins.input", _scripted_input(["s"]))  # skip, leave queued

    cli._run_review(review_providers(queue, FakeTagWriter()))

    out = capsys.readouterr().out
    assert 'fingerprint: "Drift Away" by Dobie Gray (0.62)' in out
    assert "video/channel says: Ab-Soul / Top Dawg Entertainment" in out
    assert "→ artist didn't match, kept provisional" in out


def test_skip_at_the_prompt_keeps_the_entry(monkeypatch):
    item = provisional_item("https://youtu.be/s")
    queue = FakeReviewQueue(items=[item])
    writer = FakeTagWriter()
    monkeypatch.setattr("builtins.input", _scripted_input(["s"]))

    cli._run_review(review_providers(queue, writer))

    assert writer.written == []
    assert [i.source_url for i in queue.items()] == ["https://youtu.be/s"]
