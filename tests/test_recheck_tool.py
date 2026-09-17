"""The #91 re-check harness reports today's gate outcome without writing anything."""

import importlib.util
import sys
from pathlib import Path

from muzik.domain import Match, ReviewItem, Track
from muzik.fakes import FakeFingerprinter, FakeResolver

_spec = importlib.util.spec_from_file_location(
    "recheck", Path(__file__).parent.parent / "tools" / "recheck.py"
)
recheck = importlib.util.module_from_spec(_spec)
sys.modules["recheck"] = recheck  # dataclasses resolve their module by name
_spec.loader.exec_module(recheck)


def test_a_re_checked_entry_reports_the_witness_path_and_its_ruling():
    shazam = Match(title="Bésame Mucho", artist="João Gilberto", album="", confidence=1.0)
    item = ReviewItem(
        source_url="https://youtu.be/GICw4CoJInA",
        reason="unverified: provisional Tags from the Source, Match not corroborated",
    )
    track = Track(
        source_url=item.source_url,
        audio_path=Path("/fake/GICw4CoJInA.m4a"),
        source_title="Besame Mucho",
        uploader="João Gilberto - Topic",
    )
    resolver = FakeResolver(verdict="consistent")

    row = recheck.recheck_item(
        item, track, FakeFingerprinter(shazam), FakeFingerprinter(shazam), resolver
    )

    assert row["old_reason"] == item.reason
    assert row["shazam"] == {"title": "Bésame Mucho", "artist": "João Gilberto", "tied": 0}
    assert row["path"] == "witness"
    assert row["outcome"] == "verified"
    assert row["verdict"] == "consistent"
    assert resolver.resolve_calls == []  # no album guessing on a re-check
