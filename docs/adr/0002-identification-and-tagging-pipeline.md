# Identification via Shazam, Tags via a verified waterfall

Identify each Track by **acoustic fingerprint (Shazam)**, not by parsing the Source title. A prototype over 15 mainstream and 10 obscure tracks identified 5/5 mainstream and 9/10 underground correctly, including covers, remixes, and non-English titles — fingerprinting hears the actual recording, which title-parsing cannot.

Source **Tags and cover art from a waterfall**, not one Authority: Shazam's own metadata first; **MusicBrainz** (exact lookup by ISRC) only when Shazam's album looks non-canonical (single / EP / remix / missing); the AI **Resolver** (Claude Haiku, minimal prompt) only when still unresolved. No single source was reliable alone in testing — each failed differently (Shazam returns whatever release it matched; MusicBrainz's ISRC sometimes lands on a compilation; the Resolver can hallucinate).

Guard against confident-wrong Matches with a **Confidence gate**: cross-check the Match against the Source's own title. A Match that fails the gate — or is absent — is **not** written as verified Tags. Instead the Track gets best-effort **provisional Tags** (parsed from the Source), an "unverified" marker, and a place in the **Review queue**, where the user accepts, edits, or re-identifies it. A wrong tag written as truth is worse than an honest weak one.

## Considered alternatives

- **Shazam-only (skip MusicBrainz)** — rejected: MusicBrainz recovered the canonical album in 3/15 cases Shazam's own metadata got wrong.
- **MusicBrainz-authoritative** — rejected: it landed on compilations where Shazam's own album was right (2/15). Hence the waterfall.
- **LLM-fusion (all evidence) over LLM-minimal** — not adopted: scored identically to the minimal title+thumbnail prompt across 25 tracks. Kept in reserve for Sources whose title carries no artist/song text.
- **Opus Resolver** — not adopted: Haiku matched its accuracy at ~3.5× the speed (1.2s vs 4.3s/call).

## Consequences

- Process Tracks **concurrently**; fingerprinting is near-free (~0.4s) and MusicBrainz's 1 request/second limit is the throughput floor, so the waterfall calls it sparingly (3 calls across 10 tracks in the prototype).
- Optimized pipeline measured **0.4s/track** (tagging, concurrent; downloads add a parallelised ~3–4s/track).
- Sources can be **age-restricted** (need `--cookies`) or absent from the fingerprint database; both route to the Review queue rather than failing the batch.
- Prototype code and full result tables live on branch `prototype/identify-spike`.

## Amendment (#38, ADR-0006): the Resolver also witnesses identity

The Confidence gate no longer rests on Shazam alone. A live observation run proved real Shazam confidence is **binary** (every match `1.0`, hard-coded — `docs/LEARNINGS.md`), so there is no score to lean on when the Source's own title corroborates a Match only through the channel name (an impersonator, #16) or not at all (#17). On that **uncorroborated path**, the gate now consults the **Resolver as an identity witness**: it reasons over the fingerprint Match *and* the full download — title, channel, description, tags, and thumbnail (a multimodal Haiku call) — and rules `consistent` / `inconsistent` / `unsure`. `consistent` may verify; `inconsistent` / `unsure` keep the Track unverified (Review). This is the "LLM-fusion over all evidence" alternative above, taken off reserve for exactly the case it was kept for — a Source whose title carries no independent artist signal.

- **Speed.** The witness fires **only** on the uncorroborated path; a Match the Source title independently corroborates (title + artist) still verifies with **no AI call** — the common case is unchanged. The witness call is bounded by a timeout.
- **Degradation holds.** A witness failure or timeout degrades to `unsure` (→ Review), never aborts the batch — the same batch-never-blocks contract as the album waterfall's tiers.
- This closes #16 and #17 (see ADR-0003's amendment, which supersedes the confidence-bar rule).

## Amendment (#52): every Track carries artwork — thumbnail as fallback cover art

The "a wrong tag is worse than an honest weak one" stance is relaxed **for artwork only**. The primary use is a downloaded Track with cover art on the file, yet a live 16-Track run left 5 files bare: provisional Source Tags carry no `cover_art`, and the no-fingerprint-match path wrote nothing at all. Neither cause is an edge case.

New rule, purely additive: after identification, if a Track's Tags have no `cover_art` and the Track names a `thumbnail_url`, embed the **video thumbnail**; otherwise leave the real cover untouched. A thumbnail is honest best-effort — for a sleeve-as-video upload it is often the actual cover, better than a contradicted fingerprint's art — and it only ever fills emptiness, so confident Tracks with real album art are unaffected.

- **No Track left bare.** The `match is None` path now writes best-effort Tags from the Source itself (title/artist) plus the thumbnail, still enqueued to Review as an unverified guess — no longer left untagged. Only a Source with no usable title writes nothing.
- **Degradation holds.** The thumbnail fetch is bounded by a timeout and shares the other tiers' never-block contract: a fetch miss or timeout degrades the Track to bare rather than aborting the batch.
- One shared, bounded thumbnail fetcher (`real/images.fetch_thumbnail`) now serves both the identity witness (ADR-0006) and this fallback — no duplicated fetch/timeout logic.
