"""Whole-box ('ignition') tests: drive the engine entry with fake providers."""

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


def _providers(
    match: Match | None,
    tag_writer: FakeTagWriter,
    source_title: str = "Fake Video",
    uploader: str = "",
    resolver: FakeResolver | None = None,
) -> Providers:
    return Providers(
        # The Source's own title is what the Confidence gate cross-checks the
        # Match against; drive it (and the uploader — the gate's artist witness)
        # per-test via the fake Downloader. The Resolver is the identity witness
        # the gate consults on the uncorroborated path (#38); default is a Resolver
        # that can't tell ("unsure"), so an uncorroborated Match stays unverified
        # unless a test supplies a verdict.
        downloader=FakeDownloader(
            audio_path=Path("/fake/audio.m4a"), title=source_title, uploader=uploader
        ),
        fingerprinter=FakeFingerprinter(match=match),
        authority=FakeAuthority(),
        resolver=resolver if resolver is not None else FakeResolver(),
        tagwriter=tag_writer,
    )


def test_happy_path_tags_come_from_the_fingerprinter():
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Monologues",
        cover_art=b"JPEGBYTES",
        confidence=0.99,
    )
    writer = FakeTagWriter()
    results = run(Source(url="https://youtu.be/abc"), _providers(match, writer))

    assert len(results) == 1
    result = results[0]
    assert result.status == "tagged"
    assert result.output_path is not None
    assert result.tags is not None
    # Tags carry the Fingerprinter's own identity + art.
    assert result.tags.title == "Envy"
    assert result.tags.artist == "Ogi"
    assert result.tags.album == "Monologues"
    assert result.tags.cover_art == b"JPEGBYTES"
    # The writer actually received those Tags.
    assert writer.written[0][1].title == "Envy"


def test_confidence_gate_verifies_a_match_that_agrees_with_the_source_title():
    # The Source's own title echoes the Match ("Envy" appears in it), so the
    # gate confirms it: verified Tags, straight from the Match, no marker.
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Monologues",
        cover_art=b"JPEGBYTES",
        confidence=0.99,
    )
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/abc"),
        _providers(match, writer, source_title="Ogi - Envy (Official Video)"),
    )

    result = results[0]
    assert result.status == "tagged"
    assert result.tags is not None
    # Confirmed → verified, and the Match's own identity is written.
    assert result.tags.verified is True
    assert result.tags.title == "Envy"
    assert result.tags.artist == "Ogi"
    assert result.tags.album == "Monologues"
    assert result.tags.cover_art == b"JPEGBYTES"
    # The writer received the verified Tags.
    assert writer.written[0][1].verified is True
    assert writer.written[0][1].title == "Envy"


def test_confidence_gate_writes_provisional_when_the_match_disagrees():
    # A confident Match whose title the Source contradicts must NOT be written
    # as truth. The Source names a different "Artist - Title"; the gate writes
    # that, best-effort and unverified, instead of the wrong Match.
    match = Match(
        title="Envy",
        artist="Ogi",
        album="Monologues",
        cover_art=b"JPEGBYTES",
        confidence=0.99,
    )
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/xyz"),
        _providers(
            match, writer, source_title="Rick Astley - Never Gonna Give You Up"
        ),
    )

    result = results[0]
    assert result.tags is not None
    # The confident-wrong Match is NOT written as verified.
    assert result.tags.verified is False
    assert result.tags.title != "Envy"
    assert result.tags.artist != "Ogi"
    # Provisional Tags are parsed from the Source ("Artist - Title").
    assert result.tags.artist == "Rick Astley"
    assert result.tags.title == "Never Gonna Give You Up"
    # The Match's cover art is not carried onto an unverified Track.
    assert result.tags.cover_art is None
    # The writer received the provisional, unverified Tags — never the Match's.
    assert writer.written[0][1].verified is False
    assert writer.written[0][1].title == "Never Gonna Give You Up"


def test_confidence_gate_falls_back_to_the_uploader_for_a_titleless_artist():
    # When the Source title has no artist before the dash, the artist falls back
    # to the Track's uploader (#11). An official-artist channel of the form
    # "Rick Astley - Topic" normalises to "Rick Astley", which becomes the
    # provisional artist while the title is recovered from the Source.
    match = Match(title="Envy", artist="Ogi", album="Monologues", confidence=0.99)
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/nnn"),
        _providers(
            match,
            writer,
            source_title=" - Never Gonna Give You Up",
            uploader="Rick Astley - Topic",
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is False
    assert result.tags.title == "Never Gonna Give You Up"
    assert result.tags.artist == "Rick Astley"


def test_confidence_gate_rejects_a_match_whose_artist_contradicts_the_source():
    # The single-word-title false-accept: a Match title ("Love") that the Source
    # title happens to echo, but by a *different* artist. Title agreement alone
    # is not enough — the Source names "Adele", the Match claims "Lana Del Rey".
    # The title's own parse doesn't corroborate the artist, so the witness is now
    # consulted (#42); it rules `inconsistent`, so the Match must NOT be stamped
    # verified. The Source's own identity is written instead, provisional.
    match = Match(
        title="Love",
        artist="Lana Del Rey",
        album="Lust for Life",
        cover_art=b"JPEGBYTES",
        confidence=0.99,
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")
    results = run(
        Source(url="https://youtu.be/abc"),
        _providers(
            match,
            writer,
            source_title="Adele - Love (Official Audio)",
            resolver=resolver,
        ),
    )

    result = results[0]
    assert result.tags is not None
    # The witness was consulted on this apparent contradiction (#42).
    assert resolver.witness_calls == [match]
    # Witness dissented → not verified.
    assert result.tags.verified is False
    assert result.tags.artist != "Lana Del Rey"
    # The Source's own artist/title is written, best-effort.
    assert result.tags.artist == "Adele"
    assert result.tags.title == "Love"
    # The wrong Match's art is not carried onto an unverified Track.
    assert result.tags.cover_art is None


def test_confidence_gate_verifies_a_reversed_source_title_via_the_witness():
    # #42, the track-11 shape (playlist PLBLcoq9Bb-FU): the Source names the song
    # and artist in *reversed* order — "Buscando La Verdad - Ricky Campanelli" — so
    # the dumb "Artist - Title" split reads the song ("Buscando La Verdad") as the
    # artist. The title agrees but that parse doesn't corroborate the fingerprint's
    # artist ("Dj Ricky Campanelli", also carrying a "Dj" prefix), so the witness is
    # consulted. It reads the whole video, rules `consistent`, and the Track verifies
    # with the FINGERPRINT's identity — never the reversed Source parse.
    match = Match(
        title="Buscando La Verdad",
        artist="Dj Ricky Campanelli",
        album="Buscando La Verdad",
        cover_art=b"JPEGBYTES",
        confidence=1.0,
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    results = run(
        Source(url="https://youtu.be/t11"),
        _providers(
            match,
            writer,
            source_title="BUSCANDO LA VERDAD - RICKY CAMPANELLI & JIMMY BOSCH (2018)",
            uploader="YAMI PERLAZA III",
            resolver=resolver,
        ),
    )

    result = results[0]
    assert result.tags is not None
    # The witness was consulted on the apparent (but false) contradiction.
    assert resolver.witness_calls == [match]
    # Verified with the fingerprint's tags, NOT the reversed "Artist - Title" parse.
    assert result.tags.verified is True
    assert result.tags.artist == "Dj Ricky Campanelli"
    assert result.tags.title == "Buscando La Verdad"
    assert result.tags.cover_art == b"JPEGBYTES"


def test_confidence_gate_never_consults_the_witness_on_a_title_disagreement():
    # #42 (speed): a genuine contradiction — the Source's title names a *different*
    # recording than the Match — must stay off the AI path, so the added witness cost
    # stays bounded (#38). No witness call; the Source's own identity is written.
    match = Match(
        title="Envy", artist="Ogi", album="Monologues", cover_art=b"ART", confidence=1.0
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")  # would verify — must not be asked
    results = run(
        Source(url="https://youtu.be/dis"),
        _providers(
            match,
            writer,
            source_title="Rick Astley - Never Gonna Give You Up",
            resolver=resolver,
        ),
    )

    result = results[0]
    assert result.tags is not None
    # The title disagreed outright — no AI call.
    assert resolver.witness_calls == []
    assert result.tags.verified is False
    assert result.tags.artist == "Rick Astley"
    assert result.tags.title == "Never Gonna Give You Up"


def test_confidence_gate_verifies_when_the_uploader_supplies_the_artist():
    # An official-artist upload: the Source title is bare ("Never Gonna Give You
    # Up", no "Artist -"), and the only artist witness is the "Rick Astley - Topic"
    # channel — assertable, not independent. This is the uncorroborated path, so
    # the identity witness rules (#38). A genuine channel → consistent → verified.
    match = Match(
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        album="Whenever You Need Somebody",
        cover_art=b"JPEGBYTES",
        confidence=0.99,
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    results = run(
        Source(url="https://youtu.be/dQw4"),
        _providers(
            match,
            writer,
            source_title="Never Gonna Give You Up (Official Music Video)",
            uploader="Rick Astley - Topic",
            resolver=resolver,
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.tags.artist == "Rick Astley"
    assert result.tags.title == "Never Gonna Give You Up"
    # The witness was consulted — the channel alone can't verify (#38).
    assert resolver.witness_calls == [match]


def test_confidence_gate_normalises_a_vevo_channel_into_the_artist_witness():
    # A label channel "AdeleVEVO" normalises to "Adele" — but a channel name is
    # assertable, so this is still the uncorroborated path. With the witness ruling
    # consistent, the normalised channel is trusted and the Match verifies.
    match = Match(title="Hello", artist="Adele", album="25", confidence=0.99)
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/hi"),
        _providers(
            match,
            writer,
            source_title="Hello (Official Video)",
            uploader="AdeleVEVO",
            resolver=FakeResolver(verdict="consistent"),
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.tags.artist == "Adele"


def test_confidence_gate_keeps_the_match_unverified_when_there_is_no_signal():
    # No usable second witness: the Source title is bare and the uploader is an
    # uninformative generic channel. The Match cannot be corroborated *or*
    # contradicted, so its Tags are kept but left unverified (Review queue) —
    # never clobbered with garbage parsed from an empty title.
    match = Match(
        title="Envy", artist="Ogi", album="Monologues", cover_art=b"ART", confidence=0.99
    )
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/zzz"),
        _providers(match, writer, source_title="Envy", uploader="MyMusicChannel"),
    )

    result = results[0]
    assert result.tags is not None
    # Kept, not clobbered: the Match's own identity survives, just unverified.
    assert result.tags.verified is False
    assert result.tags.title == "Envy"
    assert result.tags.artist == "Ogi"
    assert result.tags.album == "Monologues"


def test_confidence_gate_routes_an_uploader_only_match_to_review_when_the_witness_dissents():
    # The channel-impersonation hole (#16), now closed by the identity witness: the
    # Source title merely echoes the Match's title, and the only artist witness is
    # the uploader — a channel *named* after the artist, which anyone can set. The
    # (retired) confidence bar can't catch this — Shazam confidence is binary. The
    # witness rules on the full evidence; an `inconsistent` verdict keeps the Match
    # out of the verified Tags.
    match = Match(
        title="Hello",
        artist="Adele",
        album="25",
        cover_art=b"JPEGBYTES",
        confidence=1.0,
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")
    results = run(
        Source(url="https://youtu.be/imp"),
        _providers(
            match,
            writer,
            source_title="Hello (Official Video)",
            uploader="Adele",
            resolver=resolver,
        ),
    )

    result = results[0]
    assert result.tags is not None
    # Witness dissented → not verified, queued.
    assert result.tags.verified is False
    assert result.reason is not None
    assert resolver.witness_calls == [match]
    # The Match is kept (not clobbered with garbage), just left for review.
    assert result.tags.title == "Hello"
    assert result.tags.artist == "Adele"


def test_confidence_gate_verifies_when_the_source_title_itself_backs_the_artist_without_the_witness():
    # The independence path: when the Source's own title carries the artist
    # ("Adele - Hello"), that is a witness the channel can't fake — so the Match is
    # verified on the fast path with NO AI call, regardless of confidence (#38).
    match = Match(
        title="Hello",
        artist="Adele",
        album="25",
        cover_art=b"JPEGBYTES",
        confidence=1.0,
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")  # would reject — must not be asked
    results = run(
        Source(url="https://youtu.be/ind"),
        _providers(
            match, writer, source_title="Adele - Hello (Official Video)", resolver=resolver
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.tags.artist == "Adele"
    assert result.tags.title == "Hello"
    # Fast path: the witness is never consulted, even though it would have dissented.
    assert resolver.witness_calls == []


def test_confidence_gate_verifies_an_uploader_only_match_when_the_witness_agrees():
    # The other side of the witness: same uploader-only shape (channel "Adele"
    # supplies the artist the bare title doesn't), but a `consistent` verdict — a
    # genuine artist channel. The witness is trusted and the Match verifies.
    match = Match(
        title="Hello",
        artist="Adele",
        album="25",
        cover_art=b"JPEGBYTES",
        confidence=1.0,
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="consistent")
    results = run(
        Source(url="https://youtu.be/vev"),
        _providers(
            match,
            writer,
            source_title="Hello (Official Video)",
            uploader="Adele",
            resolver=resolver,
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.tags.artist == "Adele"
    assert result.tags.title == "Hello"
    assert resolver.witness_calls == [match]


def test_a_provisional_track_carries_the_rejected_match_conflict():
    # #24: a gate failure must surface *why*. The fingerprint heard a different
    # artist for a common title; the gate correctly kept it provisional, and the
    # result now carries the rejected Match and the Source witnesses it conflicted
    # with, so the output can show the conflict rather than a lone terse reason.
    match = Match(title="Drift Away", artist="Dobie Gray", album="Drift Away", confidence=0.62)
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")  # the witness settles the clash (#42)
    results = run(
        Source(url="https://youtu.be/x"),
        _providers(
            match,
            writer,
            source_title="Ab-Soul - Drift Away",
            uploader="Top Dawg Entertainment",
            resolver=resolver,
        ),
    )

    result = results[0]
    assert result.tags is not None and result.tags.verified is False
    conflict = result.conflict
    assert conflict is not None
    # What the fingerprint heard — identity + confidence.
    assert conflict.heard.title == "Drift Away"
    assert conflict.heard.artist == "Dobie Gray"
    assert conflict.heard.confidence == 0.62
    # The Source witnesses it conflicted with.
    assert conflict.source_artist == "Ab-Soul"
    assert conflict.uploader == "Top Dawg Entertainment"
    # The why now names the witness's ruling, not a mechanical artist mismatch (#42).
    assert "witness" in conflict.why


def test_a_verified_track_carries_no_conflict():
    # The gate confirmed the Match, so there is nothing to explain.
    match = Match(title="Envy", artist="Ogi", album="Monologues", confidence=0.99)
    writer = FakeTagWriter()
    results = run(
        Source(url="https://youtu.be/abc"),
        _providers(match, writer, source_title="Ogi - Envy (Official Video)"),
    )

    assert results[0].conflict is None


def test_confidence_gate_ignores_stopwords_in_title_agreement():
    # #41: a lone grammatical stopword ("The") present in the fingerprint's title
    # but not the Source's must not sink title agreement. Observed live: fingerprint
    # "The Vibes Is Right" vs video "Vibes Is Right" was dropped to Review over the
    # single word "The". With stopwords ignored it corroborates on the fast path.
    match = Match(
        title="The Vibes Is Right", artist="Barrington Levy", album="Robin Hood", confidence=1.0
    )
    writer = FakeTagWriter()
    resolver = FakeResolver(verdict="inconsistent")  # would reject — must not be asked
    results = run(
        Source(url="https://youtu.be/blv"),
        _providers(
            match,
            writer,
            source_title="Barrington Levy - Vibes Is Right (Here I Come)",
            resolver=resolver,
        ),
    )

    result = results[0]
    assert result.tags is not None
    assert result.tags.verified is True
    assert result.tags.artist == "Barrington Levy"
    assert result.tags.title == "The Vibes Is Right"
    # Fast path: corroborated by the title itself, so no AI call.
    assert resolver.witness_calls == []


def test_no_match_routes_to_the_review_queue():
    writer = FakeTagWriter()
    results = run(Source(url="https://youtu.be/xyz"), _providers(None, writer))

    assert len(results) == 1
    result = results[0]
    assert result.tags is None
    assert result.output_path is None
    assert result.status == "review"
    assert result.reason == "no fingerprint match"
    # No Match was heard, so there is no rejected-Match conflict to show (#24) —
    # the plain reason stands on its own.
    assert result.conflict is None
    # Nothing was written for an unidentified Track.
    assert writer.written == []
