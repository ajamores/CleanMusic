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
