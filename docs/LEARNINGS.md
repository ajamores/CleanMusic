# Learnings

Paid-for mistakes, so no agent repeats them. One entry per failure, **trigger-first** —
a lesson only helps if you recognize the situation before you're in it.

Keep this short and curated. An entry earns its place only if repeating the mistake would
actually cost something; prune ones that a guardrail (a pin, a CI check, a type) now prevents
mechanically. A landfill of lessons gets ignored exactly like a bloated board does.

Format:

```
## <short title>
- Trigger: <the situation, before the mistake>
- Failure (<date>): <what went wrong>
- Rule: <what to do instead>
```

---

## yt-dlp / shazamio on Python 3.14
- Trigger: creating the venv, or a `shazamio-core` build fails from source
- Failure (2026-08-20): `uv venv` defaulted to Python 3.14; `shazamio-core` ships no 3.14 wheel and its Rust build died, breaking the install.
- Rule: use Python 3.10/3.11 (3.11 preferred — `yt-dlp` deprecates 3.10). Now pinned in `.python-version`, so `uv` picks it automatically. See `docs/DEVELOPMENT.md` for setup.

## yt-dlp needs a JavaScript runtime, or downloads silently degrade
- Trigger: yt-dlp warns `No supported JavaScript runtime could be found … some formats may be missing`, and/or a Track you recognise lands in the Review queue as "Match not corroborated" instead of verifying.
- Failure (2026-08-21): with no JS runtime on PATH, yt-dlp fell back to a deprecated extraction path and pulled a lower-quality audio format. The weaker audio produced a weaker fingerprint, so the Confidence gate couldn't corroborate a Match that should have verified — the track went to review looking like a gate/identification bug when the real cause was upstream, at download.
- Rule: keep a JS runtime installed (**deno** — yt-dlp's recommended one: `curl -fsSL https://deno.land/install.sh | sh`). Treat the runtime warning as a download-quality problem first, not a fingerprint/gate problem. See `docs/DEVELOPMENT.md` requirements. Sibling of the "keep yt-dlp current" rule: media problems live upstream at the download before they reach identification.
- Update (2026-08-27, #80): on yt-dlp ≥2026.08 deno alone is **not enough** — the challenge-solver script itself is a *remote component* yt-dlp must be allowed to fetch (`remote_components: ["ejs:github"]`, now wired in the Downloader). The tell is the same warning family ("Remote components … skipped", "n challenge solving failed"), and the cost is bandwidth throttling (~66KiB/s, observed on the #66 full run), not just missing formats.

## A rate-limiting Shazam tarpits — and an unbounded recognize hangs the whole pool
- Trigger: a long batch's identification stage stops producing tag writes entirely (no ffmpeg spawns, no file mtime changes), while the process sits at low CPU with connections open; often preceded by `FailedDecodeJson` retry notes
- Failure (2026-08-27): after ~500 recognize calls in one evening, Shazam stopped answering — connections accepted, no reply ever. shazamio's `recognize` imposes no timeout, so all 4 workers wedged inside it indefinitely (confirmed by py-spy: every worker in `select()` under `recognize`); the #63 retry never fired because the calls never returned, and the batch's end-written Review queue and `.m3u8` were held hostage (~137 of 242 Tracks unprocessed).
- Rule: every external call on the batch path gets an explicit timeout — a provider that *hangs* is a failure mode distinct from one that *errors*, and retry logic is inert against it. `ShazamFingerprinter` now bounds recognize at 30s (#79). Diagnose a silent stall with `sudo env "PATH=$PATH" uvx py-spy dump --pid <pid>` before killing anything.

## Worktree agents branch from the pushed remote, not local HEAD
- Trigger: fanning out parallel worktree agents right after a local prep commit (a seam-widening refactor, a shared helper) that hasn't been pushed
- Failure (2026-08-20): committed an engine refactor to local `main` (`8001f8f`), then launched three worktree agents to build on those new seams. Every worktree branched from `origin/main` (the last *pushed* commit), so the refactor was invisible; all three rebuilt on the old structure and each independently re-touched the function the refactor was meant to isolate.
- Rule: before fanning out worktree agents, **push** any prep commit they depend on (`git push origin main`), or confirm the worktree base includes it (`git merge-base --is-ancestor <sha> <worktree-branch>`). A local-only commit does not reach a worktree.

## yt-dlp filters archived entries during extraction, not only download
- Trigger: using a `process=False` pre-flight to read a Source's video id(s) while `download_archive` is set in the same opts — e.g. to tell an archived re-run from an empty Source (#24)
- Failure (2026-08-22): two traps, both shipped through review + merge before a live run exposed them. (1) `extract_info(url, download=False, process=False)` returns `None` for an already-archived video when `download_archive` is in the opts — yt-dlp applies the archive filter during extraction, not just at download — so the check saw nothing and printed a bare `0 verified, 0 queued`. (2) After resolving archive-free, `in_download_archive` still missed a re-run when the URL carried a `list=`: the flat resolve classified the entry under the `YoutubeTab` extractor (`youtubetab <id>`) while the download had recorded it under `Youtube` (`youtube <id>`), so the extractor-keyed archive ids disagreed. Fakes hid both, because the fake encoded the same assumption the code did.
- Rule: both traps are now structurally gone — #49 / ADR-0009 removed `download_archive` from the opts entirely; re-runs are decided by a Muzik-owned id-per-line manifest via `match_filter`. What survives: confirm any yt-dlp integration assumption with a **real call**, not only a fake — the fake encodes your assumption, so it can't disprove it (that discipline caught a third contract surprise in #49: a `match_filter` skip still returns the single video's full info dict where `download_archive` returned `None`).

## shazamio's Serialize is narrower than the raw recognize payload
- Trigger: parsing Shazam's response through shazamio's `Serialize` (#58), or bumping shazamio past 0.8.1 and reaching for its typed fields
- Failure (2026-08-26): three gaps only a live probe exposed. `TrackInfo` has no `isrc` field; its `photo_url` is declared `field(init=False)`, so the factory never populates it — cover art sourced from it would silently vanish, and the #52 thumbnail fallback would mask the loss; and `Serialize.full_track` makes unrelated *envelope* fields fatal (`ResponseTrack.tag_id` has no default), so a benign envelope drift would zero every Match batch-wide.
- Rule: serialize only the `track` part (`Serialize.track(data=out["track"])`), keep isrc and cover-art URLs as raw reads on their stable named keys, and keep a raw-key fallback so a rejected shape degrades a field, not the whole Match. On any shazamio bump, re-run `pytest -m smoke` (`test_smoke_shazam`) before trusting the typed fields.

## A multimodal witness anchors on image text over every prompt instruction
- Trigger: an AI witness call includes an image whose visible text names something *near* the right answer (an album cover, a lyric-video frame), and its verdict looks confidently wrong while all the text evidence agrees
- Failure (2026-08-26): the identity witness ruled "Have You Seen Her" (`CNpdcYeSE7o`) inconsistent — against Shazam, AcoustID, *and* the channel — because the auto-generated upload's thumbnail is the album cover, printed "Where I Wanna Be" (an album that is also a famous song). Explicit prompt guidance about the format lost to the image 3/3; Haiku even attributed the cover's title to the video's title/description. Isolated by re-running the witness with and without the image.
- Rule: fix by curating the evidence, not by prompting harder — withhold an image known to be non-identity (auto-generated uploads' covers, #73). When a multimodal verdict looks wrong, re-run it *without* the image first to test for anchoring before touching the prompt.

## Shazam gives a binary match, not a graded confidence
- Trigger: any gate logic that compares `Match.confidence` to a threshold (e.g. `_UPLOADER_ONLY_MIN_CONFIDENCE = 0.9`, #16), or a ticket that says "calibrate the bar against a real confidence distribution"
- Failure (2026-08-23): #16 was parked waiting to "observe the real Shazam confidence distribution" to calibrate the 0.9 uploader-only bar. A live observation run (`tools/observe.py`, 14-track playlist) showed **every** matched Track at confidence exactly `1.000` — because `ShazamFingerprinter` hard-codes `confidence=1.0` (`src/muzik/real/fingerprinter.py`): shazamio's `recognize` returns a match or nothing, with no numeric score. There is no distribution. The 0.9 bar can never fail on a real match (1.0 ≥ 0.9 always), so the impersonator guard is **inert on real data** — a confident-wrong uploader-only Match (observed: "Trouble Man", channel "Marvin Gaye", no artist in the title) verifies regardless. Only the *fake* Fingerprinter grades confidence, which is why the offline suite made the bar look meaningful.
- Rule: treat `Match.confidence` from real Shazam as binary (1.0 = matched, else no Match), not a scalar to threshold. To separate a genuine artist channel from an impersonator (#16), a confidence bar won't do it — use an *independent* signal (Authority/MusicBrainz artist agreement, or refuse uploader-only corroboration outright), not the fingerprint's own score. Any "gather the confidence distribution" plan is a dead end until a fingerprinter that actually grades is wired.

## An AI verdict over two claims drifts onto the wrong one unless its subject is pinned
- Trigger: a witness/judge prompt hands the model more than one candidate (a primary identification plus a second opinion), and a verdict contradicts its own rationale
- Failure (2026-09-16, #88): the identity witness's rationale backed Shazam's correct Match, but its verdict scored AcoustID's junk second opinion — `inconsistent`, 2/5 live runs — and the gate, reading only the verdict, sent a good Match to Review. The prompt said "judge which (if either) fits" without ever naming what the verdict was *about*.
- Rule: name the verdict's subject outright, label the other claims "evidence only", and have the structured reply rule on the secondary claim *before* the verdict. Measure a prompt change with repeated live runs on the failing case **and** an adversarial control that must not flip — here the #16 impersonator: the first fix verified it 1/6, which the benign controls never showed.

## A keyless live run reads as a real verdict
- Trigger: a scratch script outside the repo root measures the live witness (or any AI tier), and every run comes back the same verdict — typically all `unsure`
- Failure (2026-09-16, #93): a control script in the scratchpad called `load_dotenv()`, which searches from the *script's* directory, not the cwd — so it found no `.env`, the Resolver ran keyless, and every call degraded to `unsure` by design. Thirty runs looked like a clean, unanimous measurement of old vs new prompts.
- Rule: from outside the repo, pass the path (`load_dotenv("<repo>/.env")`), and have a measurement script count degraded rulings separately (rationale `witness call failed`) rather than as verdicts. Uniform results across differing cases are a tell, not a finding.
