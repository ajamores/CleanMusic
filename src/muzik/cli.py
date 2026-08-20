"""Thin CLI adapter over the engine (ADR-0001). Knows nothing the engine doesn't."""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from muzik.domain import Source
from muzik.engine import Providers, run
from muzik.real.authority import ShazamOwnAuthority
from muzik.real.downloader import YtDlpDownloader
from muzik.real.fingerprinter import ShazamFingerprinter
from muzik.real.resolver import HaikuResolver
from muzik.real.tagwriter import Mp3TagWriter, Mp4TagWriter
from muzik.settings import OutputFormat, Settings, load_settings, save_settings

# CLI spellings for the saved formats.
_FORMAT_CHOICES = {"m4a": OutputFormat.M4A, "mp3-320": OutputFormat.MP3_320}


def _build_downloader(out_dir: Path, cookies: Path | None, fmt: OutputFormat) -> YtDlpDownloader:
    return YtDlpDownloader(out_dir=out_dir, cookies=cookies, output_format=fmt)


def _build_providers(downloader: YtDlpDownloader, fmt: OutputFormat) -> Providers:
    tagwriter = Mp4TagWriter() if fmt is OutputFormat.M4A else Mp3TagWriter()
    return Providers(
        downloader=downloader,
        fingerprinter=ShazamFingerprinter(),
        authority=ShazamOwnAuthority(),
        resolver=HaikuResolver(),
        tagwriter=tagwriter,
    )


def _resolve_format(chosen: str | None) -> OutputFormat:
    """Persist an explicit --format choice, else read the saved setting."""
    if chosen is not None:
        fmt = _FORMAT_CHOICES[chosen]
        save_settings(Settings(output_format=fmt))
        return fmt
    return load_settings().output_format


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="muzik", description="Download a YouTube video and tag it.")
    parser.add_argument("url", help="A YouTube video URL")
    parser.add_argument("--out", type=Path, default=Path("downloads"), help="Output directory")
    parser.add_argument("--cookies", type=Path, default=None, help="Cookies file for age-restricted Sources")
    parser.add_argument(
        "--format",
        choices=sorted(_FORMAT_CHOICES),
        default=None,
        help="Output format to save and use (default: last saved, or m4a)",
    )
    args = parser.parse_args()

    fmt = _resolve_format(args.format)
    downloader = _build_downloader(args.out, args.cookies, fmt)
    results = run(Source(url=args.url), _build_providers(downloader, fmt))

    for result in results:
        if result.status == "tagged" and result.tags is not None:
            print(f"tagged  {result.tags.artist} — {result.tags.title} [{result.tags.album}]")
            print(f"        {result.output_path}")
        else:
            print(f"review  {result.source_url} ({result.reason})")

    # Sources the Downloader skipped (e.g. age-restricted without --cookies) did not
    # reach the engine, but still owe the user a clear reason. The batch went on.
    for source_url, reason in downloader.skipped:
        print(f"review  {source_url} ({reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
