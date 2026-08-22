"""Thin CLI adapter over the engine (ADR-0001). Knows nothing the engine doesn't."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from muzik.domain import (
    Match,
    MatchConflict,
    ReviewDecision,
    ReviewItem,
    Source,
    Tags,
    Track,
)
from muzik.engine import Providers, ReviewOutcome, clear_review_queue, run, summarize
from muzik.providers import PlaylistInSingleModeError, Resolver
from muzik.real.authority import RateLimitedAuthority, ShazamOwnAuthority
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


def _build_downloader(
    out_dir: Path,
    cookies: Path | None,
    fmt: OutputFormat,
    expand_playlist: bool = False,
) -> YtDlpDownloader:
    return YtDlpDownloader(
        out_dir=out_dir, cookies=cookies, output_format=fmt, expand_playlist=expand_playlist
    )


def _build_providers(
    downloader: YtDlpDownloader, fmt: OutputFormat, out_dir: Path
) -> Providers:
    tagwriter = Mp4TagWriter() if fmt is OutputFormat.M4A else Mp3TagWriter()
    return Providers(
        downloader=downloader,
        fingerprinter=ShazamFingerprinter(),
        # A playlist runs Tracks concurrently (#8), so the MusicBrainz tier is
        # spaced to ~1 req/sec — its documented rate limit (ADR-0002).
        authority=RateLimitedAuthority(ShazamOwnAuthority(), min_interval=1.0),
        resolver=_build_resolver(),
        tagwriter=tagwriter,
        review_queue=JsonReviewQueue(out_dir / "review-queue.jsonl"),
    )


def _resolve_format(chosen: str | None) -> OutputFormat:
    """Persist an explicit --format choice, else read the saved setting."""
    if chosen is not None:
        fmt = _FORMAT_CHOICES[chosen]
        save_settings(Settings(output_format=fmt))
        return fmt
    return load_settings().output_format


def _describe(item: ReviewItem) -> str:
    """A one-line identity for a queue entry: its provisional Tags, or its URL."""
    if item.tags is not None:
        return f"{item.tags.artist} — {item.tags.title}"
    return item.source_url


def _conflict_lines(conflict: MatchConflict | None, indent: str = "  ") -> list[str]:
    """The rejected-Match conflict as indented lines, or none (#24).

    Shows what the fingerprint heard, the Source witnesses it conflicted with, and
    a short why — so a wrongly-rejected Match is told apart from a correctly-caught
    one, instead of a lone terse reason.
    """
    if conflict is None:
        return []
    heard = conflict.heard
    by = f" by {heard.artist}" if heard.artist else ""
    lines = [f'{indent}fingerprint: "{heard.title}"{by} ({heard.confidence:.2f})']
    witnesses = " / ".join(w for w in (conflict.source_artist, conflict.uploader) if w)
    if witnesses:
        lines.append(f"{indent}video/channel says: {witnesses}")
    lines.append(f"{indent}→ {conflict.why}")
    return lines


class _StdinReviewPrompter:
    """Asks the user, over stdin, what to do with each Review-queue entry (#7).

    Offers only the actions an entry supports: accept needs provisional Tags to
    verify; manual and hint need a file on disk to write to or re-fingerprint.
    An empty answer, or EOF, skips — leaving the entry in the queue.
    """

    def decide(self, item: ReviewItem) -> ReviewDecision:
        can_accept = item.tags is not None
        can_tag = item.audio_path is not None or item.output_path is not None
        print(f"\n{_describe(item)}\n  ({item.reason})")
        options = "  ".join(
            filter(
                None,
                [
                    "(a)ccept" if can_accept else "",
                    "(m)anual" if can_tag else "",
                    "(h)int" if can_tag else "",
                    "(s)kip",
                ],
            )
        )
        try:
            choice = input(f"  {options}? ").strip().lower()
        except EOFError:
            return ReviewDecision(action="skip")
        if choice in ("a", "accept") and can_accept:
            return ReviewDecision(action="accept")
        if choice in ("m", "manual") and can_tag:
            return ReviewDecision(action="manual", tags=self._read_tags())
        if choice in ("h", "hint") and can_tag:
            hint = input("    correct 'Artist - Title': ").strip()
            if hint:
                return ReviewDecision(action="hint", hint=hint)
        return ReviewDecision(action="skip")

    def _read_tags(self) -> Tags:
        return Tags(
            title=input("    title:  ").strip(),
            artist=input("    artist: ").strip(),
            album=input("    album:  ").strip(),
        )


def _print_outcome(outcome: ReviewOutcome) -> None:
    if outcome.cleared and outcome.result is not None and outcome.result.tags is not None:
        tags = outcome.result.tags
        print(f"tagged  {tags.artist} — {tags.title}")
    elif outcome.action == "hint":
        print(f"still queued  {_describe(outcome.item)} (hint did not re-identify it)")
    else:
        print(f"kept    {_describe(outcome.item)}")


def _run_review(providers: Providers) -> int:
    """List the Review queue and work through it interactively (#7)."""
    entries = providers.review_queue.items()
    if not entries:
        print("The Review queue is empty.")
        return 0
    print(f"Review queue ({len(entries)}):")
    for item in entries:
        # Reason OR conflict, never both (as in the batch output): a structured
        # conflict already explains why, so the terse reason would only repeat it.
        if item.conflict is not None:
            print(f"  {_describe(item)}")
            for line in _conflict_lines(item.conflict, indent="    "):
                print(line)
        else:
            print(f"  {_describe(item)}  ({item.reason})")
    outcomes = clear_review_queue(providers, _StdinReviewPrompter())
    print()
    for outcome in outcomes:
        _print_outcome(outcome)
    cleared = sum(1 for o in outcomes if o.cleared)
    print(f"\n{cleared} cleared, {len(outcomes) - cleared} still queued")
    return 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="muzik", description="Download a YouTube video and tag it.")
    parser.add_argument("url", nargs="?", help="A YouTube video URL")
    parser.add_argument(
        "--review",
        action="store_true",
        help="Work through the Review queue instead of downloading",
    )
    parser.add_argument("--out", type=Path, default=Path("downloads"), help="Output directory")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="How many Tracks of a playlist to process at once (default: engine's)",
    )
    parser.add_argument("--cookies", type=Path, default=None, help="Cookies file for age-restricted Sources")
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Expand a playlist link (default: take just the Track, ignoring an attached list)",
    )
    parser.add_argument(
        "--format",
        choices=sorted(_FORMAT_CHOICES),
        default=None,
        help="Output format to save and use (default: last saved, or m4a)",
    )
    args = parser.parse_args()

    fmt = _resolve_format(args.format)
    downloader = _build_downloader(args.out, args.cookies, fmt, expand_playlist=args.playlist)
    providers = _build_providers(downloader, fmt, args.out)

    if args.review:
        return _run_review(providers)
    if args.url is None:
        parser.error("a YouTube URL is required (or pass --review to clear the queue)")

    run_kwargs = {} if args.concurrency is None else {"concurrency": args.concurrency}
    try:
        results = run(Source(url=args.url), providers, **run_kwargs)
    except PlaylistInSingleModeError as refusal:
        # A bare playlist in single mode: nothing was downloaded. Hand the choice
        # back to the user rather than running an empty batch (ADR-0004).
        print(f"refused: {refusal}")
        return 2

    for result in results:
        # A verified Track (no reason) is tagged as truth; anything with a reason
        # went to the Review queue, provisional Tags and all.
        if result.reason is None and result.tags is not None:
            print(f"tagged  {result.tags.artist} — {result.tags.title} [{result.tags.album}]")
            print(f"        {result.output_path}")
        else:
            identity = (
                f"{result.tags.artist} — {result.tags.title}"
                if result.tags is not None
                else result.source_url
            )
            print(f"review  {identity}")
            # Show the conflict — what the fingerprint heard vs what the Source says
            # — when the gate kept the Track provisional (#24). A bare reason (e.g.
            # no fingerprint match) has no conflict; print it instead.
            conflict_lines = _conflict_lines(result.conflict)
            if conflict_lines:
                for line in conflict_lines:
                    print(line)
            elif result.reason is not None:
                print(f"  {result.reason}")
            # A gate failure still writes provisional Tags to a real file; tell the
            # user where it landed so they can find it during review.
            if result.output_path is not None:
                print(f"  file: {result.output_path} (provisional)")

    # Sources the Downloader skipped (e.g. age-restricted without --cookies) did not
    # reach the engine, but were enqueued by run(); print their reason too.
    for source_url, reason in downloader.skipped:
        print(f"review  {source_url} ({reason})")

    # A re-run where every entry was already fetched pulls no Track (#24). Say so
    # explicitly, so an all-archived Source reads as "done", not a silent failure.
    for source_url in downloader.archive_skips:
        print(f"already downloaded — nothing new for {source_url}")

    summary = summarize(results, len(downloader.skipped))
    print(f"\n{summary.verified} verified, {summary.queued} queued for review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
