"""The CLI's Resolver wiring degrades gracefully without a Claude key (#4).

The real Resolver needs a Claude key (env / gitignored .env). When it is absent
the CLI must not crash on client construction — it wires a disabled Resolver and
says so — and when it is present it wires the real Haiku Resolver.
"""

from muzik.cli import _DisabledResolver, _build_resolver
from muzik.real.resolver import HaikuResolver


def test_absent_key_yields_a_disabled_resolver_with_a_notice(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    resolver = _build_resolver()

    assert isinstance(resolver, _DisabledResolver)
    assert resolver.resolve(track=None, match=None) is None  # proposes nothing
    out = capsys.readouterr().out.lower()
    assert "anthropic_api_key" in out and "disabled" in out


def test_present_key_yields_the_real_resolver(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")

    resolver = _build_resolver()

    assert isinstance(resolver, HaikuResolver)  # constructed, no API call made
