"""Unit tests for the real Resolver's identity witness (#38, ADR-0006).

Drives ``HaikuResolver.witness_identity`` with an injected fake Anthropic client —
no network — to check the reply parsing, the timeout boundary, and that any
failure degrades to an ``unsure`` verdict (ADR-0002: never block a batch). The
Track carries an empty ``thumbnail_url`` so no thumbnail fetch is attempted.
"""

from pathlib import Path

from muzik.domain import Match, Track
from muzik.real.resolver import HaikuResolver, _WITNESS_TIMEOUT_S


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Resp:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, reply: str, raises: bool) -> None:
        self._reply = reply
        self._raises = raises
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise RuntimeError("simulated API failure")
        return _Resp(self._reply)


class _FakeClient:
    """Mimics the Anthropic client surface the witness call uses."""

    def __init__(self, reply: str = "{}", raises: bool = False) -> None:
        self.messages = _Messages(reply, raises)
        self.with_options_calls: list[dict] = []

    def with_options(self, **kwargs):
        self.with_options_calls.append(kwargs)
        return self


_TRACK = Track(
    source_url="https://youtu.be/x",
    audio_path=Path("/fake/a.m4a"),
    source_title="Hello (Official Video)",
    uploader="Adele",
    description="Official audio.",
    tags=["adele", "hello"],
    thumbnail_url="",  # empty → no network fetch
)
_MATCH = Match(title="Hello", artist="Adele", album="25", confidence=1.0)


def test_witness_parses_an_inconsistent_verdict():
    client = _FakeClient(reply='{"verdict": "inconsistent", "rationale": "channel mismatch"}')
    ruling = HaikuResolver(client=client).witness_identity(_TRACK, _MATCH)

    assert ruling.verdict == "inconsistent"
    assert ruling.rationale == "channel mismatch"
    # The call was made against Haiku with the identity-checker system prompt.
    kwargs = client.messages.calls[0]
    assert kwargs["model"] == "claude-haiku-4-5"
    assert "identity checker" in kwargs["system"]
    # Text-only (no thumbnail): the user content is a single text block naming both
    # the fingerprint and the Source evidence.
    content = kwargs["messages"][0]["content"]
    assert [b["type"] for b in content] == ["text"]
    assert "Adele" in content[0]["text"] and "Hello" in content[0]["text"]


def test_witness_parses_a_consistent_verdict():
    client = _FakeClient(reply='{"verdict": "consistent", "rationale": "genuine"}')
    ruling = HaikuResolver(client=client).witness_identity(_TRACK, _MATCH)
    assert ruling.verdict == "consistent"


def test_witness_bounds_the_call_with_a_timeout():
    client = _FakeClient(reply='{"verdict": "consistent"}')
    HaikuResolver(client=client).witness_identity(_TRACK, _MATCH)
    assert client.with_options_calls == [{"timeout": _WITNESS_TIMEOUT_S}]


def test_witness_degrades_to_unsure_when_the_call_raises():
    client = _FakeClient(raises=True)
    ruling = HaikuResolver(client=client).witness_identity(_TRACK, _MATCH)
    assert ruling.verdict == "unsure"


def test_witness_degrades_to_unsure_on_an_unparseable_reply():
    client = _FakeClient(reply="I think it's probably fine?")
    ruling = HaikuResolver(client=client).witness_identity(_TRACK, _MATCH)
    assert ruling.verdict == "unsure"


def test_witness_degrades_to_unsure_on_an_unknown_verdict():
    client = _FakeClient(reply='{"verdict": "maybe", "rationale": "hedging"}')
    ruling = HaikuResolver(client=client).witness_identity(_TRACK, _MATCH)
    assert ruling.verdict == "unsure"
