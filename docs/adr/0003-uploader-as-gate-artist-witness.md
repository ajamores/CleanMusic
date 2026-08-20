# Track carries the uploader; the Confidence gate needs two witnesses

`Track` gains an `uploader` field — the Source's channel, populated by the real Downloader from yt-dlp's `uploader` (falling back to `channel`). A YouTube identity is *"Artist – Title"*, and the artist lives most reliably in the channel, not the title: yt-dlp returns `uploader: "Rick Astley"` cleanly even when its structured `artist`/`track`/`album` fields are all `None`.

The Confidence gate (ADR-0002) now cross-checks the Match on **both** title and artist. Title agreement alone accepted a confident-wrong Match whenever its title was a common word — a Match `title="Love"` verified against *any* video whose title contained "love". The artist witness is `{parsed title-artist} ∪ {normalised uploader}`, where normalising strips the auto-channel dressing (`"Rick Astley - Topic"` → `"Rick Astley"`, `"…VEVO"` → `"…"`). The same normalised uploader is the fallback artist when a Source title carries no artist before the dash.

**Deliberate softening of ADR-0002.** ADR-0002 said a Match that fails the gate *or lacks a witness* becomes provisional. That over-corrects: when the Source offers **no usable signal** — a bare title and an uninformative uploader — parsing provisional Tags from an empty title would clobber a good fingerprint result with garbage. So the gate keeps the Match's Tags in that case, merely leaving them unverified (Review queue). A Match is written provisional-from-Source only when the Source actually contradicts it *and* carries an "Artist - Title" to write instead. Bias remains toward strictness: a wrong tag written as truth is still worse than an honest weak one.

## Consequences

- `Track.uploader` is the only new field; the gate logic stays inside the engine, so the domain type carries the raw channel and normalisation is a gate concern.
- The `…VEVO` normalisation is literal (`"RickAstleyVEVO"` → `"RickAstley"`), which tokenises as one word and will not always match a spaced artist — it errs toward unverified, which the ADR endorses.
- Folding `Match.confidence` into the gate's strictness is still open (its own ticket), as is the Review-queue routing of unverified Tracks (#6).
