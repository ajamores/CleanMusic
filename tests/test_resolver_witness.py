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


def test_witness_prompt_carries_a_second_acoustic_claim_when_given():
    # #51: a second, independent acoustic identification is named in the prompt so
    # the witness can weigh two acoustic sources, not just the video's metadata.
    second = Match(title="Hello", artist="Adele", album="", confidence=1.0)
    client = _FakeClient(reply='{"verdict": "consistent"}')
    HaikuResolver(client=client).witness_identity(_TRACK, _MATCH, second)

    text = client.messages.calls[0]["messages"][0]["content"][0]["text"]
    assert "Second acoustic identification" in text
    # The system prompt tells the model how to weigh two acoustic sources.
    assert "second" in client.messages.calls[0]["system"].lower()


def test_witness_prompt_omits_the_second_claim_when_there_is_none():
    # Shazam-only: no second source ran, so the prompt names just the one.
    client = _FakeClient(reply='{"verdict": "consistent"}')
    HaikuResolver(client=client).witness_identity(_TRACK, _MATCH)  # second defaults to None

    text = client.messages.calls[0]["messages"][0]["content"][0]["text"]
    assert "Second acoustic identification" not in text


def test_witness_system_prompt_explains_the_auto_generated_album_line():
    # #73: the reproducible misread — an official "Provided to YouTube" upload
    # lists the ALBUM on its own description line, and album titles often coincide
    # with a different well-known song (title tracks). The system prompt must brief
    # the witness on that format so it never reads the album line as the song.
    client = _FakeClient(reply='{"verdict": "consistent"}')
    HaikuResolver(client=client).witness_identity(_TRACK, _MATCH)

    system = client.messages.calls[0]["system"]
    assert "Provided to YouTube" in system
    assert "album" in system.lower()


def test_witness_withholds_the_thumbnail_on_an_auto_generated_upload(monkeypatch):
    # #73, reproduced live: on "Provided to YouTube" uploads the thumbnail is the
    # album cover, and its printed title anchors the model to the album's name
    # over every textual instruction. The cover is withheld there — the witness
    # reasons over text alone — while organic uploads keep the image (ADR-0006).
    import muzik.real.resolver as resolver_mod

    fetches: list[str] = []
    monkeypatch.setattr(
        resolver_mod, "_fetch_image", lambda url: fetches.append(url) or None
    )
    client = _FakeClient(reply='{"verdict": "consistent"}')
    auto = Track(
        source_url="https://youtu.be/x", audio_path=Path("/fake/a.m4a"),
        source_title="Have You Seen Her", uploader="Donell Jones",
        description="Provided to YouTube by Arista\n\nHave You Seen Her · Donell Jones\n\nWhere I Wanna Be",
        thumbnail_url="https://img/cover.jpg",
    )
    HaikuResolver(client=client).witness_identity(auto, _MATCH)
    assert fetches == []  # album cover never fetched, never sent

    organic = Track(
        source_url="https://youtu.be/y", audio_path=Path("/fake/b.m4a"),
        source_title="Hello (Official Video)", uploader="Adele",
        description="Official audio.", thumbnail_url="https://img/frame.jpg",
    )
    HaikuResolver(client=client).witness_identity(organic, _MATCH)
    assert fetches == ["https://img/frame.jpg"]  # organic uploads keep the image
