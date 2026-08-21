# Track carries the uploader; the Confidence gate needs two witnesses

`Track` gains an `uploader` field — the Source's channel, populated by the real Downloader from yt-dlp's `uploader` (falling back to `channel`). A YouTube identity is *"Artist – Title"*, and the artist lives most reliably in the channel, not the title: yt-dlp returns `uploader: "Rick Astley"` cleanly even when its structured `artist`/`track`/`album` fields are all `None`.

The Confidence gate (ADR-0002) now cross-checks the Match on **both** title and artist. Title agreement alone accepted a confident-wrong Match whenever its title was a common word — a Match `title="Love"` verified against *any* video whose title contained "love". The artist witness is `{parsed title-artist} ∪ {normalised uploader}`, where normalising strips the auto-channel dressing (`"Rick Astley - Topic"` → `"Rick Astley"`, `"…VEVO"` → `"…"`). The same normalised uploader is the fallback artist when a Source title carries no artist before the dash.

**Deliberate softening of ADR-0002.** ADR-0002 said a Match that fails the gate *or lacks a witness* becomes provisional. That over-corrects: when the Source offers **no usable signal** — a bare title and an uninformative uploader — parsing provisional Tags from an empty title would clobber a good fingerprint result with garbage. So the gate keeps the Match's Tags in that case, merely leaving them unverified (Review queue). A Match is written provisional-from-Source only when the Source actually contradicts it *and* carries an "Artist - Title" to write instead. Bias remains toward strictness: a wrong tag written as truth is still worse than an honest weak one.

## Consequences

- `Track.uploader` is the only new field; the gate logic stays inside the engine, so the domain type carries the raw channel and normalisation is a gate concern.
- The `…VEVO` normalisation is literal (`"RickAstleyVEVO"` → `"RickAstley"`), which tokenises as one word and will not always match a spaced artist — it errs toward unverified, which the ADR endorses.
- Folding `Match.confidence` into the gate's strictness is still open (its own ticket), as is the Review-queue routing of unverified Tracks (#6).

## Amendment (#14): the two witnesses are not independent

Adding the uploader as the second witness left a hole. The witness `{parsed title-artist} ∪ {normalised uploader}` treats the channel name as evidence, but **anyone can name a channel after any artist** — a topic re-upload, a fan channel, an impersonator. So when the fingerprint returns the *wrong* Match and the Source sits on a channel named after that wrong artist, both witnesses agree and the gate stamps a wrong tag `verified`. Two witnesses, but one is a nametag the channel wrote itself — the exact false-`verified` the gate exists to prevent.

There is no test that separates a real artist channel from one merely named after the artist; a channel can *assert* an identity as easily as confirm it. So the lever is **not** independence but **confidence**: the gate is only fooled when the Match was wrong, which is the low-confidence case. Folding `Match.confidence` in (the open ticket above) closes it.

**Rule.** The Source's own title is an *independent* witness a channel cannot fake; the uploader is not. When the artist agreement rests **solely** on the uploader (the Source title does not corroborate the artist on its own), the Match is verified only if `Match.confidence >= _UPLOADER_ONLY_MIN_CONFIDENCE`. Below the bar it is kept but left unverified (Review queue). When the Source's own title independently corroborates the artist, confidence is not consulted — that path is unchanged.

- **Threshold = `0.9`.** A deliberately high bar: the channel-only path is the weakest evidence the gate accepts, so it demands the fingerprinter be near-certain. It sits below the `0.99` that fixtures and real high-confidence matches carry, so genuine official-channel uploads (`"Artist - Topic"`, `"…VEVO"`) still verify. The value is a single named constant in `engine.py`; revisit against real fingerprint-confidence distributions once the real Fingerprinter lands.
- Bias remains toward strictness (ADR-0002): a wrong tag written as truth is worse than an honest weak one, and a channel name alone is not truth.
