"""CLI batch output for ticket #24: show the conflict, name the archived no-op.

Drives ``main`` with a stubbed engine and Downloader so the rendering is exercised
without a network, and tests the ``_conflict_lines`` renderer directly.
"""

from pathlib import Path
from types import SimpleNamespace

import muzik.cli as cli
from muzik.domain import Match, MatchConflict, Tags, TrackResult


class _StubDownloader:
    """Stands in for the real Downloader post-run: only the fields ``main`` reads."""

    def __init__(self, archive_skips=None, skipped=None):
        self.archive_skips = list(archive_skips) if archive_skips else []
        self.skipped = list(skipped) if skipped else []


def _wire(monkeypatch, tmp_path, downloader, results):
    """Point ``main`` at a stub Downloader and a canned engine result list."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("muzik.cli._build_downloader", lambda *a, **k: downloader)
    # Only the fields ``main`` reads post-run: a writer that wrote no playlist here.
    monkeypatch.setattr(
        "muzik.cli._build_providers",
        lambda *a, **k: SimpleNamespace(playlist_writer=SimpleNamespace(last_written=None)),
    )
    monkeypatch.setattr("muzik.cli.run", lambda *a, **k: results)
    monkeypatch.setattr(
        "sys.argv", ["muzik", "https://youtu.be/x", "--out", str(tmp_path / "out")]
    )


def test_conflict_lines_show_heard_witnesses_and_why():
    conflict = MatchConflict(
        heard=Match(title="Drift Away", artist="Dobie Gray", album="", confidence=0.62),
        source_artist="Ab-Soul",
        uploader="Top Dawg Entertainment",
        why="artist didn't match, kept provisional",
    )
    joined = "\n".join(cli._conflict_lines(conflict))
    assert 'fingerprint: "Drift Away" by Dobie Gray (0.62)' in joined
    assert "video/channel says: Ab-Soul / Top Dawg Entertainment" in joined
    assert "→ artist didn't match, kept provisional" in joined


def test_conflict_lines_are_empty_without_a_conflict():
    assert cli._conflict_lines(None) == []


def test_a_batch_prints_the_conflict_for_a_provisional_track(monkeypatch, capsys, tmp_path):
    result = TrackResult(
        source_url="https://youtu.be/x",
        tags=Tags(title="Drift Away", artist="Ab-Soul", album="", verified=False),
        output_path=tmp_path / "x.m4a",
        status="tagged",
        reason="unverified: provisional Tags from the Source, Match not corroborated",
        conflict=MatchConflict(
            heard=Match(title="Drift Away", artist="Dobie Gray", album="", confidence=0.62),
            source_artist="Ab-Soul",
            uploader="Top Dawg Entertainment",
            why="artist didn't match, kept provisional",
        ),
    )
    _wire(monkeypatch, tmp_path, _StubDownloader(), [result])

    assert cli.main() == 0
    out = capsys.readouterr().out
    # The heading is the provisional identity, then the conflict block, then the file.
    assert "review  Ab-Soul — Drift Away" in out
    assert 'fingerprint: "Drift Away" by Dobie Gray (0.62)' in out
    assert "→ artist didn't match, kept provisional" in out
    assert f"file: {tmp_path / 'x.m4a'} (provisional)" in out


def test_an_all_archived_rerun_prints_an_explicit_nothing_new_line(monkeypatch, capsys, tmp_path):
    downloader = _StubDownloader(archive_skips=["https://youtu.be/already"])
    _wire(monkeypatch, tmp_path, downloader, [])

    assert cli.main() == 0
    out = capsys.readouterr().out
    # An explicit line, not a bare "0 verified, 0 queued".
    assert "already downloaded — nothing new for https://youtu.be/already" in out


def test_a_bare_reason_prints_without_a_conflict_block(monkeypatch, capsys, tmp_path):
    # A no-fingerprint-match Track has no conflict — its plain reason stands alone.
    result = TrackResult(
        source_url="https://youtu.be/nomatch",
        tags=None,
        output_path=None,
        status="review",
        reason="no fingerprint match",
    )
    _wire(monkeypatch, tmp_path, _StubDownloader(), [result])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "review  https://youtu.be/nomatch" in out
    assert "no fingerprint match" in out
    assert "fingerprint:" not in out  # no structured conflict block


def test_conflict_lines_quote_the_witness_rationale_when_present():
    # #74: the witness's own sentence — the explanation the #66 slice run lacked.
    conflict = MatchConflict(
        heard=Match(title="Have You Seen Her", artist="Donell Jones", album="", confidence=1.0),
        source_artist="",
        uploader="Donell Jones",
        why="the identity witness ruled the Match inconsistent with the video, kept provisional",
        witness_rationale="the cover names the album, not the song",
    )
    joined = "\n".join(cli._conflict_lines(conflict))
    assert 'witness: "the cover names the album, not the song"' in joined


def test_conflict_lines_omit_the_witness_line_without_a_rationale():
    conflict = MatchConflict(
        heard=Match(title="Drift Away", artist="Dobie Gray", album="", confidence=0.62),
        source_artist="Ab-Soul",
        uploader="",
        why="title didn't match, kept provisional",
    )
    assert not any("witness:" in line for line in cli._conflict_lines(conflict))
