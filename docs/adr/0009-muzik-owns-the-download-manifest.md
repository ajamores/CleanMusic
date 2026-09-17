# Muzik owns the download manifest; yt-dlp's archive is retired to read-only

**Status: Accepted (2026-08-26).** Re-run detection — "this Track was already fetched, skip it" (#8/#24) — is decided by a Muzik-owned manifest (`.muzik-manifest.txt`, one video id per line), not by yt-dlp's `download_archive`. yt-dlp's old `.download-archive.txt` is kept as a frozen, read-only source of pre-existing ids. Decided in #49.

## The problem

Idempotency piggy-backed on yt-dlp's download archive: a `<extractor> <id>` file that yt-dlp both wrote and consulted. That coupling put re-run correctness at the mercy of yt-dlp internals, and it shipped two live bugs past a green offline suite (docs/LEARNINGS.md):

- **#28** — with `download_archive` in the opts, yt-dlp filters archived entries during *extraction*, not just download, so an archive-aware pre-flight saw `None` where a video was.
- **#29** — the archive is keyed by extractor, and the same video keys differently by URL shape (`Youtube` vs `YoutubeTab` for a `list=`-decorated URL), so yt-dlp's own `in_download_archive` missed a re-run.

The workaround (resolve archive-free, match by id against the file's last field) worked, but still *read* yt-dlp's format and still let yt-dlp write it — both free to shift under us on any upgrade, and this repo's policy is to keep yt-dlp current (LEARNINGS: 403s mean update first).

## Options considered

1. **Keep the by-id workaround, add smoke coverage per URL shape.** Defends the coupling rather than removing it; every yt-dlp upgrade re-opens the question.
2. **Own the archive format ourselves.** A Muzik-side manifest keyed purely by video id — "already fetched" *means* the video id, so key by exactly that and nothing else.
3. **Document the assumptions, pin a version floor.** Labels the risk without reducing it.

Option 2 was chosen: the whole bug category came from interpreting someone else's file.

## The decision

- **The manifest is Muzik's**: `.muzik-manifest.txt` beside the Tracks, one video id per line. Nothing else is encoded — no extractor, no URL shape.
- **Skipping goes through `match_filter`**: Muzik tells yt-dlp what to skip (id in manifest → skip reason), instead of yt-dlp consulting its own file. The filter takes the `incomplete` form, so flat playlist entries are skipped before their pages are re-extracted — the cost profile `download_archive` had, kept (pipeline speed is a stated concern).
- **Recording goes through `post_hooks`**: after all postprocessing — the point yt-dlp's own archive recorded at — the landed file's stem (the id, per the `%(id)s.%(ext)s` outtmpl) is appended to the manifest. Manifest bookkeeping never raises: a failed append degrades to a re-fetch next run, never an aborted batch (ADR-0002 / #32).
- **The re-run report comes from the filter's own skips.** When a download pulls nothing and the filter skipped at least one entry, the Source is reported as "already downloaded" (`archive_skips`, #24). The old shape — a second, archive-free flat resolve of the Source compared against the archive — is deleted: it leaned on the same extraction internals (lazy `process=False` generators, flat-entry keying) this decision exists to stop trusting, and cost a network round-trip per empty result.
- **The legacy archive is frozen, not migrated.** `.download-archive.txt` is still read (last field of each line, unioned in) so pre-#49 fetches stay recognised — but with `download_archive` gone from the opts, yt-dlp never writes it again, so its format can no longer drift. No migration step, nothing to run once, fully backwards compatible.

## A live-verified subtlety

Confirmed by smoke test, not assumed (LEARNINGS: the fake encodes your assumption): a `match_filter` skip suppresses only the *download* — a skipped single video's info dict is still returned in full, where `download_archive` returned `None`. The Downloader therefore tracks the ids its filter skipped per call and drops them at entry-mapping, or a re-run would emit a Track pointing at audio that was never fetched. The fake `YoutubeDL` in the offline suite models exactly this contract.

## Consequences

- Re-run detection now depends on one Muzik-owned file whose format cannot change without a Muzik commit. The #28 trap is structurally gone (`download_archive` is no longer in the opts at all, so extraction-time filtering cannot recur); the #29 trap has nothing to key on (no extractor in the manifest).
- `_all_archived` / `_resolve_entry_ids` — the hazard area #49 named — are gone entirely, and with them the last archive-related use of `extract_info`. Re-run reporting is now a local set-membership check, so an all-archived re-run costs no extra network.
- The yt-dlp surface Muzik relies on narrows to two documented, stable hooks (`match_filter`, `post_hooks`) — both covered live by `tests/test_smoke_yt_dlp.py` (fresh fetch, `list=`-decorated re-run, playlist re-run via flat entries, legacy-archive re-run).
- A library downloaded before #49 needs nothing done to it: the frozen legacy read keeps its ids honoured forever.
- The manifest is append-only and human-readable; deleting a line is the supported way to force a re-fetch of one Track.

## Amendment (#65): a Track is recorded once processed, not once downloaded

"Recording goes through `post_hooks`" is superseded. The post hook recorded a Track the moment its file landed, before identification and tagging, so a batch that died mid-run left its downloaded-but-untagged Tracks in the manifest. The next run skipped them and the files stayed untagged. This bit on the #66 full run: ~137 orphaned Tracks, recovered only by hand-editing the manifest.

- **The engine records, after the outcome is on disk.** `Downloader.record_processed(track)` appends the id once the Track's Review entry and `.m3u8` line are flushed. It is the last step per Track, on the engine's single drain thread (#64). A Track whose processing *crashed* (#62) is not recorded. A crash is not a deliberate outcome (a provider timeout, #79, raises), so a plain re-run retries it; the price is a repeat Review entry if it crashes again.
- **The post hook still runs, in memory only.** It adds the id to this run's skip set, so a video listed twice in one run is fetched once. The copy that landed still maps to a Track even though its duplicate was filter-skipped, or it would never be processed or recorded. Nothing reaches disk until the Track is processed.
- **Unchanged:** one id per line, `match_filter` skipping, deleting a line to re-fetch, the frozen legacy archive, and bookkeeping that never raises.
- **Trade-off, accepted:** a crash between download and processing now costs a re-download on the next run (usually cheap, since yt-dlp finds the file already on disk). The old failure was worse: an orphaned file that nothing flagged.
