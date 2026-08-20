# Prototype verdict — identification & tagging

**Question:** How should Muzik identify a downloaded Track and source its Tags — and can it be fast?

**Scripts (throwaway):**
- `identify_spike.py` — arm comparison over 5 → 15 songs
- `timing_spike.py` — per-stage latency, Opus vs Haiku Resolver
- `optimized_pipeline.py` — the chosen design, concurrent, on 10 obscure local tracks

## What the data said

| Finding | Evidence |
|---|---|
| **Shazam is the identifier** | 5/5 mainstream, 9/10 obscure; correct on covers, remixes, non-English |
| **No single Authority is reliable** | Shazam-own wrong 3/15, MusicBrainz wrong 2/15 — different failures → waterfall |
| **Resolver earns a narrow role** | Only source to get *Cheese*, *Heroes & Villains*; but can hallucinate → must verify |
| **LLM-minimal ≈ LLM-fusion** | Identical across 25 tracks; fusion held in reserve for title-less Sources |
| **Haiku ≈ Opus accuracy, 3.5× faster** | 1.2s vs 4.3s/call |
| **MusicBrainz = 2 calls, not 9** | `browse_releases` with release-groups in one call; 1 req/s is the throughput floor |
| **Confident-wrong is the real risk** | Dave East loosie → matched a different song confidently → needs a Confidence gate |

## Chosen design (see ADR-0002)

```
Source → download → fingerprint (Shazam) → identity + ISRC
   → album waterfall: Shazam-own → MusicBrainz (if album looks off) → Haiku Resolver (if still off)
   → Confidence gate: Match vs Source title
        pass  → write verified Tags
        fail  → provisional Tags + "unverified" marker + Review queue
   → run Tracks concurrently
```

**Measured speed:** 0.4s/track (tagging, 10 concurrent). Downloads add a parallelised ~3–4s/track.

**Cost:** pennies — Haiku Resolver fires only on disagreement (3/10 tracks in the obscure run).

**Edge cases → Review queue:** age-restricted Sources (need `--cookies`), tracks absent from the fingerprint DB, failed Confidence gate.
