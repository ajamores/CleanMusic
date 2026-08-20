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
from muzik.real.tagwriter import Mp4TagWriter


def _build_providers(out_dir: Path, cookies: Path | None) -> Providers:
    return Providers(
        downloader=YtDlpDownloader(out_dir=out_dir, cookies=cookies),
        fingerprinter=ShazamFingerprinter(),
        authority=ShazamOwnAuthority(),
        resolver=HaikuResolver(),
        tagwriter=Mp4TagWriter(),
    )


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="muzik", description="Download a YouTube video and tag it.")
    parser.add_argument("url", help="A YouTube video URL")
    parser.add_argument("--out", type=Path, default=Path("downloads"), help="Output directory")
    parser.add_argument("--cookies", type=Path, default=None, help="Cookies file for age-restricted Sources")
    args = parser.parse_args()

    results = run(Source(url=args.url), _build_providers(args.out, args.cookies))

    for result in results:
        if result.status == "tagged" and result.tags is not None:
            print(f"tagged  {result.tags.artist} — {result.tags.title} [{result.tags.album}]")
            print(f"        {result.output_path}")
        else:
            print(f"review  {result.source_url} ({result.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
