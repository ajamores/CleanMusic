"""Opt-in smoke test against REAL yt-dlp (#30).

Every other test is offline (docs/DEVELOPMENT.md): the yt-dlp seam is exercised
only through a fake ``YoutubeDL``, and a fake can only confirm the behaviour its
author assumed — it cannot disprove a wrong assumption about the real tool. That
gap shipped two live #24 bugs past a green 100+ test suite and three reviews:

  * #28 — ``extract_info(download=False, process=False)`` returns ``None`` for an
    already-archived video when ``download_archive`` is in the opts (yt-dlp filters
    archived entries during *extraction*, not just download).
  * #29 — a ``list=``-decorated URL classifies under the ``YoutubeTab`` extractor
    while the download recorded it under ``Youtube``, so an extractor-keyed archive
    check misses the re-run.

These cases drive the real pipeline on the paths #24 touched. They are a pre-merge
tool, not a CI gate: each **skips** (never fails) when the environment can't
support it — no network, or no ``yt-dlp`` / ``ffmpeg`` / JS runtime (docs/LEARNINGS
"yt-dlp needs a JavaScript runtime"). Run them with ``pytest -m smoke``.

Assertions are on **shape** — a Track count, ``archive_skips``, an audio file on
disk — never on the identity a live fingerprint/metadata lookup returns, so a
re-fingerprint or a metadata edit upstream doesn't flake the run.
"""

from __future__ import annotations

import shutil
import socket

import pytest

from muzik.cli import _build_downloader, _build_providers
from muzik.domain import Source
from muzik.engine import run
from muzik.real.downloader import YtDlpDownloader
from muzik.settings import OutputFormat

pytestmark = pytest.mark.smoke

# --- Pinned fixtures ----------------------------------------------------------
# Small, stable, licence-clean Blender shorts (Caminandes, CC-BY). A takedown is a
# one-line fix here. The playlist is an *ad-hoc* ``watch_videos`` list built from
# two pinned ids, so it depends only on those videos existing — not on some third
# party keeping a curated playlist alive at a fixed size.
_VIDEO_ID = "SkVqJ1SGeL0"  # "Caminandes 3: Llamigos" (~2.5 min)
_SECOND_VIDEO_ID = "Z4C82eyhwgU"  # "Caminandes 2: Gran Dillama"
_VIDEO_URL = f"https://www.youtube.com/watch?v={_VIDEO_ID}"
#: A ``list=``-decorated form of the SAME video — the #29 surface, and the reason
#: this whole file exists. Confirmed against real yt-dlp (LEARNINGS: verify, don't
#: assume): the plain download records the id under the ``youtube`` extractor,
#: while the archive-free resolve of this URL keys it under ``YoutubeTab`` even in
#: single mode — the split that made the old ``in_download_archive`` miss the
#: re-run. A stable public playlist id (Blender Open Movies), not an
#: auto-generated ``RD`` mix, keeps the case deterministic and region-independent.
_STABLE_PLAYLIST_ID = "PL6B3937A5D230E335"
_VIDEO_URL_WITH_LIST = (
    f"https://www.youtube.com/watch?v={_VIDEO_ID}&list={_STABLE_PLAYLIST_ID}"
)
#: An ad-hoc 2-item playlist built from two pinned ids — depends only on those
#: videos existing, not on a third party keeping a curated list at a fixed size.
_PLAYLIST_URL = (
    f"https://www.youtube.com/watch_videos?video_ids={_VIDEO_ID},{_SECOND_VIDEO_ID}"
)


def _skip_reason() -> str | None:
    """Why these can't run here, or ``None`` when they can.

    (yt-dlp itself is a hard dependency of the package — it is imported at module
    top — so there is no "yt-dlp missing" case to guard: the import would fail
    first. The external toolchain and network are what actually vary.)

    Only ``deno`` counts as a JS runtime: yt-dlp auto-enables only deno, and the
    Downloader passes no ``--js-runtimes`` override, so a node/bun on PATH is not
    one the real download can actually use. Without it yt-dlp degrades to a
    deprecated path (docs/LEARNINGS) — better to skip than to flake.
    """
    for tool in ("ffmpeg", "deno"):
        if shutil.which(tool) is None:
            return f"{tool} not on PATH (see docs/DEVELOPMENT.md)"
    try:
        socket.create_connection(("www.youtube.com", 443), timeout=5).close()
    except OSError:
        return "no network to YouTube"
    return None


@pytest.fixture(autouse=True)
def _require_real_yt_dlp() -> None:
    reason = _skip_reason()
    if reason is not None:
        pytest.skip(reason)


@pytest.fixture
def out_dir(tmp_path):
    """A fresh downloads dir per test — the archive lives beside the Tracks in it."""
    return tmp_path / "downloads"


def _audio_files(out_dir) -> list:
    """The audio Tracks yt-dlp actually wrote to disk (any extension it extracted)."""
    return [p for p in out_dir.iterdir() if p.suffix in (".m4a", ".mp3")]


def test_smoke_fresh_download_is_processed_end_to_end(out_dir):
    # Case 1: a fresh Source runs the whole real pipeline — download → fingerprint →
    # gate → write — and lands one processed Track with an audio file on disk. It is
    # the one case wired through the CLI's own builders (_build_downloader /
    # _build_providers), so the smoke test covers the exact provider graph the CLI
    # ships; cases 2 and 3 need only the Downloader in isolation. Assert the shape
    # (one result, a file), never the identity: a live fingerprint may verify or send
    # it to review, both of which count as processed.
    downloader = _build_downloader(out_dir, None, OutputFormat.M4A)
    providers = _build_providers(downloader, OutputFormat.M4A, out_dir)

    results = run(Source(url=_VIDEO_URL), providers)

    assert len(results) == 1
    assert downloader.archive_skips == []  # a genuine fresh fetch, not a re-run
    assert _audio_files(out_dir), "yt-dlp downloaded no audio file"


def test_smoke_archived_rerun_records_nothing_new(out_dir):
    # Case 2 — the #28/#29 regression surface. A fresh fetch, then the SAME Source
    # re-run in a `list=`-decorated form (the #29 cross-extractor id). The second run
    # must pull no Track and record the Source on `archive_skips` — not silently
    # print a bare 0/0, and not route it to `skipped` as a failure.
    first = YtDlpDownloader(out_dir=out_dir)
    fresh = first.download(Source(url=_VIDEO_URL))
    assert len(fresh) == 1, "the first fetch should download the Track"

    # A fresh Downloader instance, as a second CLI invocation would be; the archive
    # persists in the out dir between runs.
    rerun = YtDlpDownloader(out_dir=out_dir)
    again = rerun.download(Source(url=_VIDEO_URL_WITH_LIST))

    assert again == []
    assert rerun.archive_skips == [_VIDEO_URL_WITH_LIST]
    assert rerun.skipped == []  # nothing-new is not a failure


def test_smoke_playlist_expansion_yields_both_tracks(out_dir):
    # Case 3: `--playlist` (expand_playlist=True) on a 2-item playlist expands to two
    # Tracks. Single mode would collapse a list to one; expansion is the difference.
    downloader = YtDlpDownloader(out_dir=out_dir, expand_playlist=True)

    tracks = downloader.download(Source(url=_PLAYLIST_URL))

    ids = {t.audio_path.stem for t in tracks}
    assert ids == {_VIDEO_ID, _SECOND_VIDEO_ID}
    assert downloader.skipped == []
