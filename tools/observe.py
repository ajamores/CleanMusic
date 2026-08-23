"""Observation harness — records the real identification signal for #16/#17/#38.

It began as the data-gathering run that unparked #16 and #17 (the finding that
real Shazam confidence is binary lives in `docs/LEARNINGS.md`). It now also
records the identity witness that resolved them (#38, ADR-0006): whether the gate
took the corroborated fast path or consulted the witness, and what verdict the
witness returned. The offline suite fakes all of this, so only a live run shows
the real distribution.

This drives a real batch (real Shazam Fingerprinter, real Haiku Resolver) and,
without changing engine behaviour, writes one JSONL row per Track capturing what
the pipeline computed but never emits: the fingerprint result, the gate breakdown
(title agreement, artist corroboration, fast path vs. witness path), whether the
album Resolver was reached and what it proposed, and the identity witness verdict.

The two providers are wrapped in thin *recording* seams that log then delegate;
the gate breakdown is recomputed from ``muzik.engine``'s own pure helpers, so the
row reports exactly what the real gate decided — nothing is re-implemented.

Run:  python tools/observe.py "<playlist-or-video-url>" [--out retest/observe]
Output (into a gitignored dir): observations.jsonl + a printed summary.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from muzik.domain import IdentityRuling, Match, Source, Track
from muzik.engine import (
    Providers,
    _agrees,
    _artist_corroborates,
    _identity_tokens,
    _normalise_uploader,
    _source_artist,
    run,
)
from muzik.real.authority import RateLimitedAuthority, ShazamOwnAuthority
from muzik.real.downloader import YtDlpDownloader
from muzik.real.fingerprinter import ShazamFingerprinter
from muzik.real.playlist import M3u8PlaylistWriter
from muzik.real.resolver import HaikuResolver
from muzik.real.review_queue import JsonReviewQueue
from muzik.real.tagwriter import Mp4TagWriter


@dataclass
class _Record:
    """What the recording seams captured for one Track, keyed by its source URL."""

    track: Track
    match: Match | None = None
    #: True once the Resolver seam ran for this Track (the album was unresolved and
    #: the waterfall reached the AI tier). False means the Resolver was never asked.
    resolver_reached: bool = False
    #: The album the Resolver proposed, or None when it declined (or was not reached).
    resolver_album: str | None = None
    #: True once the identity witness ran for this Track (#38 — the gate reached the
    #: uncorroborated path). False means the fast path verified or contradicted it.
    witness_reached: bool = False
    #: The witness's verdict when it ran, else None.
    witness_verdict: str | None = None
    #: Wall-clock of the witness call (ms) — the added per-uncorroborated-Track cost
    #: the #38 acceptance asks to measure. None when the witness never ran.
    witness_ms: float | None = None


class _Sink:
    """Thread-safe collector the recording seams write into, keyed by source URL.

    The per-Track pipeline may run across a thread pool, so writes take a lock. In
    practice the harness runs at concurrency 1 for clean, ordered records; the lock
    keeps it correct if that is raised.
    """

    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}
        self._lock = threading.Lock()

    def note_match(self, track: Track, match: Match | None) -> None:
        with self._lock:
            self._records[track.source_url] = _Record(track=track, match=match)

    def note_resolver(self, track: Track, proposed: Match | None) -> None:
        with self._lock:
            record = self._records.get(track.source_url)
            if record is None:  # defensive: identify always runs first in the pipeline
                return
            record.resolver_reached = True
            record.resolver_album = proposed.album if proposed is not None else None

    def note_witness(self, track: Track, ruling: IdentityRuling, elapsed_ms: float) -> None:
        with self._lock:
            record = self._records.get(track.source_url)
            if record is None:  # defensive: identify always runs first
                return
            record.witness_reached = True
            record.witness_verdict = ruling.verdict
            record.witness_ms = elapsed_ms

    def get(self, source_url: str) -> _Record | None:
        return self._records.get(source_url)


class _RecordingFingerprinter:
    """Wraps a real Fingerprinter: records the Match (and its confidence), then
    returns it unchanged so the gate sees exactly what it would without us."""

    def __init__(self, inner: ShazamFingerprinter, sink: _Sink) -> None:
        self._inner = inner
        self._sink = sink

    def identify(self, track: Track) -> Match | None:
        match = self._inner.identify(track)
        self._sink.note_match(track, match)
        return match


class _RecordingResolver:
    """Wraps a real Resolver: records whether it was reached and what it proposed
    (or that it declined), then returns its verdict unchanged."""

    def __init__(self, inner: HaikuResolver, sink: _Sink) -> None:
        self._inner = inner
        self._sink = sink

    def resolve(self, track: Track, match: Match | None) -> Match | None:
        proposed = self._inner.resolve(track, match)
        self._sink.note_resolver(track, proposed)
        return proposed

    def witness_identity(self, track: Track, match: Match) -> IdentityRuling:
        t0 = time.perf_counter()
        ruling = self._inner.witness_identity(track, match)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self._sink.note_witness(track, ruling, elapsed_ms)
        return ruling


def _gate_breakdown(track: Track, match: Match) -> dict:
    """Recompute the Confidence gate's structure from the engine's own helpers.

    Mirrors ``_confidence_gate`` (ADR-0006): the fast path verifies when the
    Source's own title corroborates both title and artist; otherwise, when the
    title echoes the Match but names no artist of its own, the identity witness is
    consulted (``consults_witness``). Reports the branch, not the final verdict —
    the witness's ruling and the final outcome are recorded separately.
    """
    uploader_artist = _normalise_uploader(track.uploader)
    source_artist = _source_artist(track.source_title)
    title_witness = _identity_tokens(source_artist)
    witness = title_witness | _identity_tokens(uploader_artist)
    title_agrees = _agrees(match, track.source_title)
    corroborated_by_title = _artist_corroborates(match, title_witness)
    artist_corroborated = _artist_corroborates(match, witness)
    uploader_only = artist_corroborated and not corroborated_by_title
    corroborated_fast_path = title_agrees and corroborated_by_title
    consults_witness = title_agrees and not title_witness
    return {
        "source_artist": source_artist,
        "uploader_artist": uploader_artist,
        "title_agrees": title_agrees,
        "artist_corroborated": artist_corroborated,
        "corroborated_by_title": corroborated_by_title,
        "uploader_only": uploader_only,
        # The fast, AI-free verify path (the common case, #38).
        "corroborated_fast_path": corroborated_fast_path,
        # The uncorroborated path where the identity witness is consulted.
        "consults_witness": consults_witness,
    }


def _row(result, record: _Record | None) -> dict:
    """One JSONL observation row: fingerprint + gate breakdown + Resolver behaviour."""
    track = record.track if record is not None else None
    match = record.match if record is not None else None
    row: dict = {
        "source_url": result.source_url,
        "source_title": track.source_title if track else None,
        "uploader": track.uploader if track else None,
        "matched": match is not None,
        # Final outcome, straight from the engine: verified when reason is None.
        "final_verified": result.reason is None,
        "review_reason": result.reason,
    }
    if match is not None:
        row["fingerprint"] = {
            "title": match.title,
            "artist": match.artist,
            "album": match.album,
            "isrc": match.isrc,
            "confidence": match.confidence,
        }
        row["gate"] = _gate_breakdown(track, match)
    if record is not None:
        row["resolver"] = {
            "reached": record.resolver_reached,
            # None with reached=True means the Resolver was asked and declined —
            # itself a signal for #17.
            "proposed_album": record.resolver_album,
            "declined": record.resolver_reached and record.resolver_album is None,
        }
        row["witness"] = {
            "reached": record.witness_reached,
            "verdict": record.witness_verdict,
            "ms": round(record.witness_ms, 1) if record.witness_ms is not None else None,
        }
    if result.tags is not None:
        row["final_tags"] = {
            "artist": result.tags.artist,
            "title": result.tags.title,
            "album": result.tags.album,
            "verified": result.tags.verified,
        }
    return row


def _summarize(rows: list[dict], run_seconds: float) -> str:
    """A short human-readable tally over the rows — the shape of the distribution."""
    matched = [r for r in rows if r["matched"]]
    verified = sum(1 for r in rows if r["final_verified"])
    fast_path = sum(1 for r in matched if r["gate"]["corroborated_fast_path"])
    consults = sum(1 for r in matched if r["gate"]["consults_witness"])
    resolver_reached = sum(1 for r in rows if r.get("resolver", {}).get("reached"))
    resolver_declined = sum(1 for r in rows if r.get("resolver", {}).get("declined"))
    resolver_proposed = resolver_reached - resolver_declined
    witness_reached = sum(1 for r in rows if r.get("witness", {}).get("reached"))

    def _verdict(name: str) -> int:
        return sum(1 for r in rows if r.get("witness", {}).get("verdict") == name)

    # The added AI cost the #38 acceptance asks to measure: per-witnessed-Track and
    # the whole-run wall-clock. Fast-path Tracks contribute nothing (no witness call).
    witness_ms = [r["witness"]["ms"] for r in rows if r.get("witness", {}).get("ms") is not None]
    avg_witness = f"{sum(witness_ms) / len(witness_ms):.0f} ms" if witness_ms else "n/a"
    total_witness = f"{sum(witness_ms) / 1000:.1f} s" if witness_ms else "0 s"

    lines = [
        f"Tracks observed:            {len(rows)}",
        f"  fingerprint matched:      {len(matched)}",
        f"  finally verified:         {verified}",
        f"  routed to review:         {len(rows) - verified}",
        "",
        "Confidence gate paths (matched Tracks) — ADR-0006:",
        f"  corroborated fast path:   {fast_path}   (verified, no AI call)",
        f"  consulted the witness:    {consults}   (the uncorroborated path)",
        "",
        "Identity witness — the #16/#17 signal (#38):",
        f"  reached:                  {witness_reached}",
        f"  consistent:               {_verdict('consistent')}",
        f"  inconsistent:             {_verdict('inconsistent')}",
        f"  unsure:                   {_verdict('unsure')}",
        "",
        "Speed — the #38 acceptance measurement:",
        f"  whole-run wall-clock:     {run_seconds:.1f} s",
        f"  witness calls made:       {len(witness_ms)}",
        f"  avg per witnessed Track:  {avg_witness}",
        f"  total witness time:       {total_witness}   (the added AI cost this run)",
        "",
        "Album Resolver behaviour:",
        f"  reached (album unresolved after catalogs): {resolver_reached}",
        f"  proposed an album:        {resolver_proposed}",
        f"  declined (null):          {resolver_declined}",
    ]
    return "\n".join(lines)


def _build_providers(sink: _Sink, out_dir: Path, expand_playlist: bool) -> Providers:
    """Real providers, with the Fingerprinter and Resolver wrapped to record.

    M4A throughout (the default format) — the observation is about identification,
    not the output codec. Mirrors ``cli._build_providers`` otherwise.
    """
    downloader = YtDlpDownloader(out_dir=out_dir, expand_playlist=expand_playlist)
    return Providers(
        downloader=downloader,
        fingerprinter=_RecordingFingerprinter(ShazamFingerprinter(), sink),
        authority=RateLimitedAuthority(ShazamOwnAuthority(), min_interval=1.0),
        resolver=_RecordingResolver(HaikuResolver(), sink),
        tagwriter=Mp4TagWriter(),
        review_queue=JsonReviewQueue(out_dir / "review-queue.jsonl"),
        playlist_writer=M3u8PlaylistWriter(out_dir),
    )


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="observe", description="Record real gate signal for tickets #16 / #17."
    )
    parser.add_argument("url", help="A YouTube playlist or video URL to observe")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("retest/observe"),
        help="Output dir for audio + observations (gitignored). Default: retest/observe",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Tracks processed at once. Default 1 for clean, ordered records.",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Treat the URL as a single video (default: expand a playlist).",
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "note: no ANTHROPIC_API_KEY — the Resolver tier is unavailable, so the "
            "#17 signal will be empty. Set it to observe Resolver behaviour."
        )

    args.out.mkdir(parents=True, exist_ok=True)
    sink = _Sink()
    providers = _build_providers(sink, args.out, expand_playlist=not args.single)

    started = time.perf_counter()
    results = run(Source(url=args.url), providers, concurrency=args.concurrency)
    run_seconds = time.perf_counter() - started

    rows = [_row(result, sink.get(result.source_url)) for result in results]
    out_path = args.out / "observations.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(_summarize(rows, run_seconds))
    print(f"\nrows written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
