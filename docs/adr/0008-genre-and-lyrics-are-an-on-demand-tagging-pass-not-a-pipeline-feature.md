# Genre (and lyrics) are tagged by an on-demand pass over the library, not by the pipeline

**Status: Accepted (2026-08-25).** Muzik's pipeline writes the tags that *identify* a Track — title, artist, album, artwork, track number, year (ADR-0002, the Authority waterfall). Genre and lyrics are deliberately **not** part of that pipeline. They are done, when wanted, as an ad-hoc pass over an already-tagged library, driven directly by Claude Code against the files on disk.

## The problem

The core tags are the ones that make a library coherent, and they are built and verified automatically. Genre and lyrics are *nice-to-haves* on top. The instinct was to add them to the Authority waterfall the same way — a genre source, a lyrics provider — but the cost/benefit is poor:

- **Genre** has no authoritative source. Shazam and MusicBrainz frequently disagree ("Pop" vs "synth-pop"), and neither is wrong. Wiring a source in buys a messy, subjective string that still needs human judgement — so the automation adds failure surface without settling the actual question.
- **Lyrics** needs a *new* provider entirely (LRCLIB, Genius, Musixmatch — keys, rate limits, licensing), a synced-vs-plain fork, per-recording matching, and a large text payload per file. It is a feature in its own right, not an increment on the existing waterfall.

## The decision

Neither is added to the pipeline. Instead:

- **Genre** is assigned by an on-demand pass: open the library's files with mutagen (already a dependency — the same library the TagWriter uses), read the existing artist/album Tags, and have Claude propose a genre per artist/album from what it already knows, then write it back. No lookup chain, no new provider, no code to develop — the capability exists today by invoking Claude Code against the library.
- The default delivery is **review-then-write**: Claude produces an artist/album → proposed-genre list for approval first, and only writes after the user vetoes the wrong calls. Once the calls are trusted, it may write directly. This keeps the conservative bias — a human settles the subjective field, the tool just does the mechanical read/write fast.
- **Lyrics** stay out of scope for now. If they are ever wanted, the same on-demand shape is the first thing to try before any provider is built.

## Consequences

- **No pipeline change, no new dependency, nothing to build.** The pipeline's job stays "identify and tag correctly"; genre is a curation step layered on afterward, on demand.
- The `Tags` dataclass and the Authority waterfall are unaffected — a genre field there was considered and rejected here, so a future contributor need not wonder why identification doesn't set genre.
- The pass edits real music files in place. It is run against a backed-up library, with an approval step before the first write, precisely because it operates outside the pipeline's verified-tag guarantees.
- Reversible: if a genuine authoritative genre source ever appears, this ADR can be superseded and genre folded into the waterfall. Nothing here forecloses that; it just declines to pay for it now.

## Amendment — Shazam already carries genre, and can carry lyrics (2026-08-26)

Inspecting shazamio's schema against the version installed here corrects two assumptions in the original decision:

- **Genre is not sourceless.** The Shazam response already carries `genres_primary` — a single coarse genre, for free, on the same call we already make. We discard it today (see #58, which makes it reachable by name). This doesn't overturn the decision — one coarse genre that still disagrees with MusicBrainz is exactly the subjective field the on-demand pass exists to settle — but it lowers the cost: the on-demand pass can *seed* from `genres_primary` and refine, rather than assign from nothing.
- **Lyrics are not necessarily a new-provider problem.** The original text claimed lyrics need a dedicated provider (LRCLIB/Genius/Musixmatch). shazamio models a `LyricsSection` (`type: "LYRICS"`, `text: List[str]`, with a `beacon_data` provider), reachable via `Shazam.track_about(track_id=...)` — a *second* call on the track id that `recognize()` already returns. So Shazam itself may supply lyrics.

Two caveats keep lyrics out of scope for now, unchanged:

1. **Plain, not synced.** The `LyricsSection` is a list of lines, not time-synced `.lrc` — the karaoke form is the part that would earn its keep, and it isn't here. And a modelled field is not a guaranteed-populated one; coverage varies per track.
2. **A second network call + licensing.** `track_about` doubles the Shazam round-trips per Track on the hot path (pipeline speed is a stated concern), and redistributing lyrics carries a licensing/ToS question separate from the code.

**Net:** the decision stands — genre and lyrics remain off the pipeline, done on demand — but the *starting materials* are cheaper than first recorded. If lyrics are ever pursued, `track_about`'s `LyricsSection` is the first thing to try before any external provider, and it would want to be a lazy, opt-in, measured call — not added to the default recognise path.
