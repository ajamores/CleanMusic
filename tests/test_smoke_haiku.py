"""Opt-in smoke test against the REAL Anthropic API — the Haiku witness (#46).

The identity witness (``HaikuResolver.witness_identity``, ADR-0006) is the signal
the Confidence gate verifies on for an uncorroborated Track. Offline it is exercised
only through a fake Resolver, and a fake encodes the author's assumption about the
model's replies — it cannot disprove a wrong one (docs/LEARNINGS.md). Two things a
fake can never establish are checked here against the live service:

  * a real call returns a **valid verdict** for a constructed Track/Match, and
  * a real SDK failure **degrades to ``unsure``** rather than raising (ADR-0002: a
    batch never blocks) — the degrade path proven against the anthropic SDK's own
    exception types, not a fake's ``raise``.

It costs pennies, so — per the ticket — it is gated on ``ANTHROPIC_API_KEY`` (and a
route to the API). Like the other smoke tests it is a pre-merge tool, not a CI gate:
it **skips** (never fails) when the key or network is absent. Run with
``pytest -m smoke``.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import get_args

import anthropic
import pytest

from muzik.domain import IdentityVerdict, Match, Track
from muzik.real.resolver import HaikuResolver

pytestmark = pytest.mark.smoke

load_dotenv = pytest.importorskip("dotenv").load_dotenv

#: The verdicts a ruling may carry — read from the domain Literal (as the resolver
#: does), so this test can't drift from the set the code accepts.
_VALID_VERDICTS = frozenset(get_args(IdentityVerdict))


def _skip_reason() -> str | None:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "no ANTHROPIC_API_KEY"
    try:
        socket.create_connection(("api.anthropic.com", 443), timeout=5).close()
    except OSError:
        return "no network to Anthropic"
    return None


@pytest.fixture(autouse=True)
def _require_api() -> None:
    reason = _skip_reason()
    if reason is not None:
        pytest.skip(reason)


def _track() -> Track:
    """A Track whose own evidence is self-consistent with the Match below."""
    return Track(
        source_url="https://youtu.be/x",
        audio_path=Path("/does/not/matter.m4a"),  # the witness reads metadata, not audio
        source_title="Michael Jackson - Billie Jean",
        uploader="Michael Jackson",
        description="Michael Jackson's official audio for Billie Jean, from Thriller.",
        thumbnail_url="",  # no thumbnail → the witness reasons over text alone, no fetch
    )


def _match() -> Match:
    return Match(title="Billie Jean", artist="Michael Jackson", album="Thriller", confidence=1.0)


def test_smoke_witness_returns_a_valid_verdict():
    ruling = HaikuResolver().witness_identity(_track(), _match())

    # Shape only: assert the verdict is one the code accepts and the rationale is a
    # string — NEVER that it is specifically "consistent". A live model may rule
    # "unsure" on thin evidence, which is a valid outcome, not a failure.
    assert ruling.verdict in _VALID_VERDICTS
    assert isinstance(ruling.rationale, str)


def test_smoke_witness_degrades_to_unsure_on_a_real_sdk_failure():
    # A deliberately invalid key makes the REAL anthropic SDK raise its real
    # authentication error mid-call; witness_identity must swallow it into "unsure"
    # (ADR-0002), never let it abort a batch. This is the whole point of the smoke
    # test — a fake's ``raise`` can't prove the degrade path handles the SDK's own
    # exception types. (Costs nothing: the request is rejected before generation.)
    broken = HaikuResolver(client=anthropic.Anthropic(api_key="sk-ant-invalid-forced-failure"))

    ruling = broken.witness_identity(_track(), _match())

    assert ruling.verdict == "unsure"
