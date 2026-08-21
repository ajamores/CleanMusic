"""Thin CLI adapter over the engine (ADR-0001). Knows nothing the engine doesn't."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from muzik.domain import Match, Source, Track
from muzik.engine import Providers, run, summarize
from muzik.providers import Resolver
from muzik.real.authority import ShazamOwnAuthority
from muzik.real.downloader import YtDlpDownloader
from muzik.real.fingerprinter import ShazamFingerprinter
from muzik.real.resolver import HaikuResolver
from muzik.real.review_queue import JsonReviewQueue
from muzik.real.tagwriter import Mp3TagWriter, Mp4TagWriter
from muzik.settings import OutputFormat, Settings, load_settings, save_settings

# CLI spellings for the saved formats.
_FORMAT_CHOICES = {"m4a": OutputFormat.M4A, "mp3-320": OutputFormat.MP3_320}


class _DisabledResolver:
    """The AI Resolver tier, switched off when no Claude key is configured.

    The key comes from the environment / gitignored .env (``load_dotenv`` in
    ``main``). Without it the last waterfall tier proposes nothing rather than
    crashing the batch on client construction — Tracks it would have resolved get
    provisional Tags and a place in the Review queue instead (CONTEXT.md: the
    batch never blocks).
    """

    def resolve(self, track: Track, match: Match | None) -> Match | None:
        return None


def _build_resolver() -> Resolver:
    """The real Haiku Resolver when a Claude key is present, else a disabled one.

    An absent key is reported once, plainly, and degrades the AI tier instead of
    failing — see ``_DisabledResolver``.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "note: no ANTHROPIC_API_KEY (set it in the environment or a .env file) — "
            "the AI album Resolver is disabled; Tracks needing it go to review."
        )
        return _DisabledResolver()
    return HaikuResolver()


def _build_downloader(out_dir: Path, cookies: Path | None, fmt: OutputFormat) -> YtDlpDownloader:
    return YtDlpDownloader(out_dir=out_dir, cookies=cookies, output_format=fmt)


def _build_providers(
    downloader: YtDlpDownloader, fmt: OutputFormat, out_dir: Path
) -> Providers:
    tagwriter = Mp4TagWriter() if fmt is OutputFormat.M4A else Mp3TagWriter()
    return Providers(
        downloader=downloader,
        fingerprinter=ShazamFingerprinter(),
        authority=ShazamOwnAuthority(),
        resolver=_build_resolver(),
        tagwriter=tagwriter,
        review_queue=JsonReviewQueue(out_dir / "review-queue.json"),
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
    results = run(Source(url=args.url), _build_providers(downloader, fmt, args.out))

    for result in results:
        # A verified Track (no reason) is tagged as truth; anything with a reason
        # went to the Review queue, provisional Tags and all.
        if result.reason is None and result.tags is not None:
            print(f"tagged  {result.tags.artist} — {result.tags.title} [{result.tags.album}]")
            print(f"        {result.output_path}")
        else:
            print(f"review  {result.source_url} ({result.reason})")
            # A gate failure still writes provisional Tags to a real file; tell the
            # user where it landed so they can find it during review.
            if result.output_path is not None:
                print(f"        {result.output_path} (provisional)")

    # Sources the Downloader skipped (e.g. age-restricted without --cookies) did not
    # reach the engine, but were enqueued by run(); print their reason too.
    for source_url, reason in downloader.skipped:
        print(f"review  {source_url} ({reason})")

    summary = summarize(results, len(downloader.skipped))
    print(f"\n{summary.verified} verified, {summary.queued} queued for review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
