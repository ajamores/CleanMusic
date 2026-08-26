# Artist-name normalisation is conservative in v1: feature credits and Unicode form only

**Status: Accepted — implemented (#47, 2026-08-25).** Spec user story #26 (issue #1) promised artist names kept consistent across the library. This ADR fixes the *scope* of the first pass: a normaliser (`muzik.artist.normalise_artist`) is applied to the artist Tag before every write, but it changes a name only where the change cannot merge two distinct artists. It unifies feature-credit form, de-duplicates repeated credits, NFC-normalises Unicode, and collapses whitespace — and deliberately does **not** fold case, strip diacritics, or romanise. Those are deferred, not rejected.

## The problem

US#26 wanted `Beyoncé` / `Beyonce` / `BEYONCÉ`, `Artist feat. X` / `Artist ft. X` / `Artist (feat. X)`, and romanised-vs-native names all written consistently. It was unbuilt: the only normalisation that existed was `engine._normalise_uploader`, used *inside* the Confidence gate to compare witnesses — nothing normalised the artist actually **written** into a Track's Tags.

## The governing constraint

From the ticket and CONTEXT.md: **a wrong "normalisation" that merges two distinct artists is worse than an untidy-but-correct name.** Merging is unrecoverable rot (two artists become one in the library); an untidy name is a cosmetic miss a later, catalog-backed pass can still fix. So the bar for a transform is not "is it valuable?" but "can it ever merge two different artists?" — and anything that can, waits.

## What that admits, and what it excludes

| Transform | v1? | Why |
|---|---|---|
| **Feature-credit form** — `ft`/`ft.`/`featuring`/`feat` → one `feat.`, brackets dropped, repeated credits de-duped | **In** | The credit *keyword* carries no identity, so unifying it can't merge artists. The primary artist (before the first credit) is left verbatim — never split on `&`/`,` — and a featured segment is never split on its own commas, so `Simon & Garfunkel` and `Tyler, The Creator` survive whole. |
| **Unicode NFC** — combining marks → pre-composed | **In** | Canonicalises the *encoding* of an identical visible name; never changes what the name looks like. The only safe diacritic handling. |
| **Whitespace** — collapse runs, trim | **In** | Cannot change identity. |
| **Case-folding** — `BEYONCÉ` → `Beyoncé` | **Deferred** | Intentional casing is real (`will.i.am`, `CHVRCHES`, `deadmau5`, `MØ`); blind folding corrupts them. Deciding the "right" case per artist needs a catalog. |
| **Diacritic stripping/adding** — `Beyoncé` ⇄ `Beyonce` | **Deferred** | We can't tell which spelling is canonical without a catalog; guessing merges two spellings a human may have entered deliberately. |
| **Romanisation** — native-script ⇄ Latin | **Deferred** | The fiddliest (the ticket says so), and the most merge-prone. Needs a catalog and a transliteration policy. |

The three deferred rows share one prerequisite: a **known-artist catalog** (MusicBrainz artist lookup) to fold safely. That is a larger piece of work; this ADR keeps v1 shippable and correct rather than blocking it on the catalog. So `Beyoncé` and `Beyonce` are *not* unified in v1 — the accepted untidy-but-correct outcome.

## Consequences

- The normaliser is a pure function (`muzik.artist`), unit-tested directly (`tests/test_artist.py`) — the fiddly branch logic the ticket flagged as worth cracking the box open for.
- It is applied at the engine's single write choke point (`engine._write`), which returns the canonicalised Tags, so the file, the Review queue entry, and a `--playlist` run's `.m3u8` all carry the same artist — verified and provisional paths alike.
- A future catalog-backed pass can layer case/diacritic/romanisation folding on top without revisiting this one: this pass only ever *tidies*, never *chooses between spellings*, so the two compose.

## Amendment — the credit's *home*, not just its form (#56, 2026-08-25)

The original pass tidied a feature credit **in place** in the artist field (`Drake ft. Rihanna feat. Rihanna` → `Drake feat. Rihanna`). That fixes the *form* but leaves the credit in the wrong field: a player that groups by the artist tag still splinters one artist into `Drake`, `Drake feat. Rihanna`, `Drake feat. Future` — the very fragmentation US#26 set out to prevent, one field over. Every reference tagger (MusicBrainz/Picard, Apple Music, streaming) uses one policy: **artist = primary artist only; the featured credit lives in the track title** as `(feat. X)`. This repo already trusts MusicBrainz as its Authority, so keeping `feat.` in the artist field is a second, conflicting standard.

**Decision.** `muzik.artist.place_feature_credit(title, artist)` operates on the `(title, artist)` pair (a superset of the artist-only `normalise_artist`, which it calls first — so #47's in-place tidy still runs on every write path). When the artist carries a *clear* featured clause, it moves that clause into the title as one `(feat. X)` and reduces the artist to the primary. It is applied at the same single write choke point (`engine._write`), so verified and provisional Tags alike are covered.

**Same conservative bias, held tighter.** Moving text *between* fields is riskier than tidying one in place, so the bar to act is higher:

- **Never duplicate.** If the title already names every featured artist (Shazam sometimes supplies `(feat. X)` in the title), the credit is only *stripped* from the artist — never a second copy appended. Matched across feature forms and case-insensitively.
- **Never guess across a disagreement.** If the title carries a *different* feature clause (naming someone the artist field does not, or only partially overlapping), both fields are left as they are and the artist keeps its #47-normalised credit — an untidy pair beats a wrong cross-field edit.
- **Only a clear clause moves.** A bare `feat. X` with no primary to anchor on is left alone, exactly as `normalise_artist` leaves it.

The featured names are parsed by the same #47 machinery, so the guarantees carry over unchanged: the primary artist is never split (`Simon & Garfunkel feat. X`), and a featured segment is never split on its own commas (`feat. Tyler, The Creator`).

**Where it earns its keep.** In practice the mess appears on the YouTube-title-parsing (provisional) path; Shazam usually returns a clean primary artist already. That is the path this most affects.
