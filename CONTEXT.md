# Muzik

A personal tool that downloads audio from YouTube and writes clean, verified music tags into the resulting files.

## Language

### Input

**Source**:
A YouTube URL the user submits — either a single video or a playlist. One playlist Source yields many Tracks.
_Avoid_: link, URL, input

**Track**:
One downloaded audio file — the unit of output, and the thing that gets tagged.
_Avoid_: song, video, file

**Download manifest**:
The Muzik-owned record of already-fetched video ids — one id per line, in `.muzik-manifest.txt` beside the Tracks — so a re-run Source never re-downloads a Track it already produced (ADR-0009). Deleting a line is how one Track is deliberately re-fetched. yt-dlp's old `<extractor> <id>` archive file is frozen: read for its pre-manifest ids, never written again.
_Avoid_: archive (the retired yt-dlp file), history, cache

### Identification

**Identification**:
Determining which real-world recording a Track actually is. Kept distinct from where its tags come from. Approaches include acoustic fingerprinting, text search, and the AI Resolver.
_Avoid_: match (as a verb), lookup

**Match**:
A candidate identity for a Track, carrying a confidence. A strong Match is tagged automatically; a weak one goes to the Review queue.
_Avoid_: result, hit

**Confidence gate**:
The check that decides whether a Match is trustworthy enough to write as verified Tags. It compares the Match against the Source's own title. A Match that fails the gate — or is absent — is unverified: the Track gets provisional Tags and goes to the Review queue, and is never written as if confirmed.
_Avoid_: validation, score

**Resolver**:
The AI step that reasons over *all* available evidence for a Track at once — the fingerprint result, yt-dlp's extracted metadata (title, channel, description, tags), and the thumbnail — cross-checking them. It has two roles: as an **identity witness** it rules on whether a fingerprint's identity is consistent with that evidence (see **Identity verdict**), which the Confidence gate verifies on; and as the last tier of the **Authority** waterfall it proposes a canonical album. It does not author final Tags except as a last resort.
_Avoid_: AI, GPT, model

**Identity verdict**:
The Resolver's ruling, as an identity witness, on whether a Match fits a Track's own evidence (ADR-0006): **consistent** (the evidence backs the Match — it may verify), **inconsistent** (the evidence contradicts it — route to Review), or **unsure** (too little to tell — kept unverified, and the safe degradation when the AI call fails). The Confidence gate consults it only on the *uncorroborated* path, where the Source's own title carries no independent artist witness; a title-corroborated Match verifies with no verdict, and so does one where both fingerprinters name the same recording the title echoes — three agreeing claims the Resolver's sampled verdict may not overrule (#93).
_Avoid_: score, confidence (the verdict is not a number — Match confidence is binary)

### Output

**Authority**:
Where a Track's canonical Tags and cover art come from once it is identified. Not a single source but a waterfall — Shazam's own metadata, then MusicBrainz, then the Resolver — consulted in that order, because each is unreliable alone.
_Avoid_: source (overloaded with Source), database

**Tags**:
The metadata written into a Track's file — title, artist, album, track number, year, cover art. Tags are either verified (from a Match that passed the Confidence gate) or provisional (best-effort, drawn from the Source, pending review).
_Avoid_: metadata, ID3

**Artist normalisation**:
A conservative canonicalisation of the artist name applied just before it is written (verified and provisional Tags alike), so a library doesn't accumulate variants of one artist. v1 unifies feature-credit form (`ft.` / `featuring` / `(feat. …)` → one `feat.`), de-duplicates repeated credits, NFC-normalises Unicode, and collapses whitespace — but never folds case, strips diacritics, or romanises, because those can merge two distinct artists without a catalog (ADR-0007). It also keeps the credit in the right *field*: a clear featured-artist clause is moved out of the artist field into the title as `(feat. X)`, leaving the artist **primary-only** — the convention every reference tagger uses — but only when that move is unambiguous (never duplicating a credit the title already carries, never guessing across a disagreement). The rule: an untidy-but-correct name beats a wrong merge, and an untidy pair beats a wrong cross-field move.
_Avoid_: cleanup, dedupe (as the whole thing), fuzzy-match

**Review queue**:
The set of Tracks whose Identification was too uncertain to auto-tag. It fills during a batch and the user clears it in one pass after the batch completes — the batch itself never blocks.
_Avoid_: pending list, errors, failures

**Playlist file**:
The `.m3u8` written beside a `--playlist` run's Tracks, preserving the *grouping* — the monthly YouTube playlist those Tracks came from — as a plain list of relative paths a music library imports. It lives beside the Tracks, never in them: a Track's album Tag is its real album, so the grouping is kept separate (ADR-0005).
_Avoid_: m3u, list (as a noun for this file), grouping folder
