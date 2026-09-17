"""Integration test for acceptance criterion 1: the engine, driven through the
REAL Authority and REAL TagWriter, produces a tagged M4A on disk.

Only the two network providers (Downloader, Fingerprinter) are faked — so this
exercises the download→tag seam end to end without touching the network.
"""

from mutagen.mp4 import MP4

from muzik.domain import Match, Source, Track
from muzik.engine import Providers, run
from muzik.fakes import FakeFingerprinter, FakeResolver
from muzik.real.authority import ShazamOwnAuthority
from muzik.real.tagwriter import Mp4TagWriter


class _LocalFileDownloader:
    """Stands in for yt-dlp: yields one Track pointing at an already-local file."""

    def __init__(self, audio_path):
        self._audio_path = audio_path
        self.skipped: list[tuple[str, str]] = []
        self.playlist_title: str | None = None

    def download(self, source: Source) -> list[Track]:
        return [Track(source_url=source.url, audio_path=self._audio_path)]

    def record_processed(self, track: Track) -> None:
        pass


def test_engine_writes_a_tagged_m4a_to_disk(silent_m4a, png_1px):
    match = Match(title="Envy", artist="Ogi", album="Monologues", cover_art=png_1px, confidence=1.0)
    providers = Providers(
        downloader=_LocalFileDownloader(silent_m4a),
        fingerprinter=FakeFingerprinter(match=match),
        authority=ShazamOwnAuthority(),
        resolver=FakeResolver(),
        tagwriter=Mp4TagWriter(),
    )

    results = run(Source(url="https://youtu.be/abc"), providers)

    assert len(results) == 1
    assert results[0].status == "tagged"
    assert results[0].output_path == silent_m4a

    # The Tags really landed in the file on disk, from the Fingerprinter's Match.
    on_disk = MP4(str(silent_m4a))
    assert on_disk["\xa9nam"] == ["Envy"]
    assert on_disk["\xa9ART"] == ["Ogi"]
    assert on_disk["\xa9alb"] == ["Monologues"]
    assert bytes(on_disk["covr"][0]) == png_1px
