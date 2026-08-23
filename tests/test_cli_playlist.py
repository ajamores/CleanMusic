"""CLI wiring for ticket #22: --playlist opt-in, and the bare-playlist refusal.

The flag is per-invocation (never saved, unlike --format) and maps to the
Downloader's playlist expansion; a refused Source surfaces as a clear message and
runs no pipeline.
"""

from pathlib import Path

import pytest

from muzik.cli import _build_downloader, main
from muzik.providers import PlaylistInSingleModeError
from muzik.settings import OutputFormat, load_settings


def test_build_downloader_defaults_to_single_mode(tmp_path):
    downloader = _build_downloader(tmp_path, None, OutputFormat.M4A)
    assert downloader._build_opts()["noplaylist"] is True


def test_build_downloader_expands_playlists_when_asked(tmp_path):
    downloader = _build_downloader(tmp_path, None, OutputFormat.M4A, expand_playlist=True)
    assert downloader._build_opts()["noplaylist"] is False


def test_playlist_flag_is_not_persisted(tmp_path, monkeypatch):
    # --playlist is an intent about this URL, not a saved preference (unlike
    # --format). Running with it must leave the saved settings untouched.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("muzik.cli.run", lambda *a, **k: [])
    monkeypatch.setattr(
        "sys.argv",
        ["muzik", "https://youtu.be/abc", "--playlist", "--out", str(tmp_path / "out")],
    )

    assert main() == 0
    # No settings file was written for a playlist-only run, so the default stands.
    assert load_settings().output_format is OutputFormat.M4A


def test_cli_reports_where_the_playlist_landed(tmp_path, monkeypatch, capsys):
    # After a --playlist run, the CLI tells the user where the .m3u8 landed (#25),
    # reading it off the writer the engine drove.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    out = tmp_path / "out"

    def _run(source, providers, **kwargs):
        # Stand in for the engine driving the writer during the batch.
        providers.playlist_writer.last_written = out / "Aug 2026.m3u8"
        return []

    monkeypatch.setattr("muzik.cli.run", _run)
    monkeypatch.setattr(
        "sys.argv",
        ["muzik", "https://youtube.com/playlist?list=PL", "--playlist", "--out", str(out)],
    )

    assert main() == 0
    printed = capsys.readouterr().out
    assert "playlist" in printed
    assert "Aug 2026.m3u8" in printed


def test_a_refused_bare_playlist_is_reported_and_runs_no_pipeline(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def _refuse(*args, **kwargs):
        raise PlaylistInSingleModeError(
            "that's a playlist; pass --playlist to download all of it"
        )

    monkeypatch.setattr("muzik.cli.run", _refuse)
    monkeypatch.setattr(
        "sys.argv",
        ["muzik", "https://youtube.com/playlist?list=PL", "--out", str(tmp_path / "out")],
    )

    exit_code = main()

    out = capsys.readouterr().out
    assert exit_code != 0
    assert "--playlist" in out
    assert "verified" not in out  # no batch summary — nothing was attempted
