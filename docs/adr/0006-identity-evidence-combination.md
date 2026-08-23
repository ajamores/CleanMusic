# Identification combines all the evidence: the Resolver becomes an identity witness

**Status: Accepted (option 3) — implemented (#38, 2026-08-23).** The identity witness ships in `resolver.witness_identity` and the `_confidence_gate` uncorroborated path; the confidence bar is retired (see ADR-0002 and ADR-0003 amendments). Identity no longer rests on Shazam alone: when the fingerprint's identity is uncorroborated, the Resolver reasons over the fingerprint result *and* the full download (title, channel, description, tags, thumbnail) and rules on whether the identification is right, and the Confidence gate verifies on that verdict. Grew out of the observation run for #16/#17 (`tools/observe.py`) and the finding in `docs/LEARNINGS.md` that real Shazam confidence is binary. Implemented as the epic below (tickets A–C); this ADR is the spec.

## What the engine actually does today

Despite CONTEXT.md's definition of the **Resolver** — "reasons over *all* available evidence for a Track at once — the fingerprint result, yt-dlp's extracted metadata (title, channel, description, tags), and the thumbnail — cross-checking them to propose the best identity" — the running engine does **not** do this. Concretely (`engine._process_track`):

1. **Shazam alone decides the identity.** `fingerprinter.identify(track)` returns a Match or nothing. Nothing else proposes or seconds an identity.
2. **The Confidence gate spot-checks that identity against the Source's own text only** — the video **title** and the **channel/uploader**. If they corroborate the Match on both title and artist it is stamped `verified`; otherwise the Track keeps provisional Tags and goes to Review.
3. **MusicBrainz and the Resolver never touch identity.** They sit in the *album* waterfall (`_album_waterfall`, ADR-0002): they only fill in which **album** a song is on. The real `HaikuResolver` receives the artist and title Shazam already chose and asks one question — *"what studio album is this on?"* It cannot say "Shazam got the song wrong."
4. **The richer evidence is never even captured.** `downloader._track_from_entry` keeps only the **title**, **channel**, and **duration**. The video's description, tags, and thumbnail — which yt-dlp has in hand — are discarded, so nothing downstream could reason over them even if asked.

So the system pictured in CONTEXT.md — an AI weighing the fingerprint against the full download to judge whether the identification is right — is **unbuilt on two counts**: the evidence isn't captured, and the AI never rules on identity.

## Why this surfaces now

The observation run for #16 showed real Shazam returns a **binary** result: every match scores confidence `1.0` (it is hard-coded — Shazam has no graded score). So:

- There is **no confidence number** to lean on. The `0.9` uploader-only bar (#16) can never fail on a real match, so the impersonator guard is inert.
- The **only independent signals** available to catch a confident-wrong Shazam are (a) the Source's own metadata and (b) an AI cross-examination — which is exactly the evidence the engine currently throws away and the reasoning it never does.

Both parked tickets are the same shape: **the gate grants `verified` on evidence that is not independent of the thing it is checking** — #16 (fingerprint + a channel anyone can name, both agreeing and both wrong) and #17 (a Resolver album on a Track whose title happens to agree). Neither can be closed with a threshold. The real question is how much evidence the identity decision should combine.

## The question

When the fingerprint's identity is uncorroborated — or as a routine check on every Track — should Muzik **combine evidence to decide/verify identity** (fingerprint + the video's full metadata + thumbnail, cross-examined, per CONTEXT.md), rather than trusting Shazam alone and only spot-checking it against the title and channel?

## Options considered

1. **Status quo — Shazam-alone, gated by the Source title/channel.** Cheapest, no AI on the identity path. But a confident-wrong Shazam whose title or channel happens to corroborate it still verifies — precisely the #16 impersonator case — and there is no confidence signal to fall back on.

2. **Capture the richer evidence and widen the gate's *witnesses*.** Keep Shazam as the identifier, but (a) capture description/tags/thumbnail onto the Track, and (b) let the gate weigh an **independent Authority** (e.g. MusicBrainz artist agreement by ISRC) and the extra metadata as corroboration — not just the title/channel. Still no AI ruling on identity. Medium cost; closes much of #16 by demanding a witness a channel name can't fake.

3. **Promote the Resolver to an identity witness (the CONTEXT.md vision).** When identity is uncertain (or routinely), the AI reasons over the fingerprint result *and* the full download (title, channel, description, tags, thumbnail) and rules **consistent / inconsistent / can't tell**, which gates verification. Most capable, and the only option that lets the AI catch a wrong Shazam. Costs one AI call per checked Track and **requires option 2's capture step first**. This is what would actually close both #16 and #17.

## Consequences / prerequisites

- Options 2 and 3 both need a **downloader change first**: capture the video's description, tags, and thumbnail onto the Track (today only title/channel/duration survive). That is the gating prerequisite for any evidence-combining identity decision.
- Option 3 realigns the code with CONTEXT.md's stated definition of the Resolver; options 1 and 2 would mean **amending CONTEXT.md** to admit the Resolver is album-only.
- Whatever is chosen, `Match.confidence` from real Shazam should be treated as binary, not thresholded (see `docs/LEARNINGS.md`). #16 and #17 should be re-pointed at this ADR: their "revisit-when real confidence is observed" premise is answered — the answer is that confidence is not the signal.
