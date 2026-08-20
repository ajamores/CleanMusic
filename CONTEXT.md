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
The AI step that reasons over *all* available evidence for a Track at once — the fingerprint result, yt-dlp's extracted metadata (title, channel, description, tags), and the thumbnail — cross-checking them to propose the best identity. It proposes an identity; it does not author final Tags except as a last resort.
_Avoid_: AI, GPT, model

### Output

**Authority**:
Where a Track's canonical Tags and cover art come from once it is identified. Not a single source but a waterfall — Shazam's own metadata, then MusicBrainz, then the Resolver — consulted in that order, because each is unreliable alone.
_Avoid_: source (overloaded with Source), database

**Tags**:
The metadata written into a Track's file — title, artist, album, track number, year, cover art. Tags are either verified (from a Match that passed the Confidence gate) or provisional (best-effort, drawn from the Source, pending review).
_Avoid_: metadata, ID3

**Review queue**:
The set of Tracks whose Identification was too uncertain to auto-tag. It fills during a batch and the user clears it in one pass after the batch completes — the batch itself never blocks.
_Avoid_: pending list, errors, failures
