"""Whole-box tests for ticket #9: output-format setting + cookies for age-gated Sources.

Driven through the engine entry with fake providers, in the style of test_engine.py.
"""

from pathlib import Path

from muzik.domain import Match, Source
from muzik.engine import Providers, run
from muzik.fakes import (
    FakeAuthority,
    FakeDownloader,
    FakeFingerprinter,
    FakeResolver,
    FakeTagWriter,
)
from muzik.settings import (
    DEFAULT_FORMAT,
    OutputFormat,
    Settings,
    load_settings,
    save_settings,
)

_MATCH = Match(title="Envy", artist="Ogi", album="Monologues", confidence=0.99)


def _providers(downloader: FakeDownloader, writer: FakeTagWriter) -> Providers:
    return Providers(
        downloader=downloader,
        fingerprinter=FakeFingerprinter(match=_MATCH),
        authority=FakeAuthority(),
        resolver=FakeResolver(),
        tagwriter=writer,
    )


# --- the saved setting ---------------------------------------------------------


def test_default_saved_format_is_m4a(tmp_path):
    fmt = load_settings(tmp_path / "absent.json").output_format
    assert fmt is OutputFormat.M4A is DEFAULT_FORMAT


def test_saved_setting_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(output_format=OutputFormat.MP3_320), path)
    assert load_settings(path).output_format is OutputFormat.MP3_320


# --- format read from the setting and honoured when writing --------------------


def test_saved_m4a_setting_writes_m4a(tmp_path):
    fmt = load_settings(tmp_path / "absent.json").output_format  # default M4A
    writer = FakeTagWriter(output_format=fmt)
    results = run(
        Source(url="https://youtu.be/abc"),
        _providers(FakeDownloader(output_format=fmt), writer),
    )
    assert results[0].status == "tagged"
    assert results[0].output_path.suffix == ".m4a"


def test_saved_mp3_320_setting_flows_to_download_and_write(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(output_format=OutputFormat.MP3_320), path)
    fmt = load_settings(path).output_format

    downloader = FakeDownloader(output_format=fmt)
    writer = FakeTagWriter(output_format=fmt)
    results = run(Source(url="https://youtu.be/abc"), _providers(downloader, writer))

    assert results[0].status == "tagged"
    # The saved fallback format reached both the downloaded Track and the write.
    assert downloader.download(Source(url="x"))[0].audio_path.suffix == ".mp3"
    assert results[0].output_path.suffix == ".mp3"


# --- cookies for age-restricted Sources ----------------------------------------

_ENTRIES = [("Clean Song", False), ("Age-Gated Song", True)]


def test_cookies_let_an_age_restricted_source_download():
    downloader = FakeDownloader(cookies=Path("cookies.txt"), entries=_ENTRIES)
    results = run(Source(url="https://youtu.be/list"), _providers(downloader, FakeTagWriter()))

    assert len(results) == 2  # both entries fetched and tagged
    assert all(r.status == "tagged" for r in results)
    assert downloader.skipped == []


def test_age_restricted_without_cookies_reports_reason_and_does_not_abort_batch():
    downloader = FakeDownloader(cookies=None, entries=_ENTRIES)
    results = run(Source(url="https://youtu.be/list"), _providers(downloader, FakeTagWriter()))

    # The clean Track still processed — the batch was not aborted.
    assert len(results) == 1
    assert results[0].status == "tagged"

    # The age-restricted entry surfaced a clear reason.
    assert len(downloader.skipped) == 1
    title, reason = downloader.skipped[0]
    assert title == "Age-Gated Song"
    assert "cookies" in reason.lower()
