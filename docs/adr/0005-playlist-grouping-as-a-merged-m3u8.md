# A `--playlist` run's grouping is preserved as a merged `.m3u8`, beside the Tags

The everyday curation flow is: like videos on YouTube, gather them into a monthly playlist ("Aug 2026"), and that grouping is worth keeping. But a Track's **album Tag is its real album** — Muzik's whole job — so the grouping must live *beside* the Tags, never overwrite them. An extended-M3U file is exactly that: a plain list pointing at the Track files, which a music library imports as a real playlist. One Track can sit in two monthly lists — one file on disk, named in both — which folder-based grouping cannot do cleanly (the global download-archive skips the second copy).

So when (and only when) `--playlist` expands a Source into a playlist, Muzik writes **one `.m3u8`** in the output folder: `#EXTM3U`, then an `#EXTINF:<seconds>,<Artist> - <Title>` line and a **relative** path per landed Track, in playlist order. The file is named after the playlist's **own yt-dlp title** (filesystem-sanitized) — the same principle as ADR-0004: the classification is yt-dlp's, never Muzik URL parsing. Single mode (default, one Track) writes nothing — there is no list to preserve. Only Tracks that produced a file are listed; a failed download or a fingerprint miss leaves no dead pointer.

## Keeping the list complete across re-runs

A re-run of a grown playlist is the hard case. The download-archive (#8) means yt-dlp hands the engine only the **freshly-fetched** Tracks; the ones already downloaded don't come back, so a naively-regenerated `.m3u8` would list only this run's new Tracks and silently drop the earlier ones — the grouping would rot exactly as it grew.

The chosen mechanism: the writer **merges with any existing `.m3u8` of the same name**. The prior run's own file already records the archived Tracks' paths *and* their `#EXTINF` lines, so the writer reads it back, keeps the entries whose file still exists on disk (dropping any that vanished — no dead pointers), and appends this run's new Tracks. The merged list overwrites the file (**overwrite-to-latest**; not a versioned `List (2).m3u8`). The complete grouping is preserved without re-identifying or re-reading a single audio file.

## Considered alternatives

- **List only the freshly-fetched Tracks** — rejected: on any re-run of a grown playlist the regenerated list would drop everything already in the archive, defeating the point of preserving the grouping.
- **Re-read Tags from every file on disk to rebuild the full list** — rejected: far heavier (open and parse every archived file), and it leans on the same archive/yt-dlp interaction that has bitten this project twice (see `docs/LEARNINGS.md`). The prior `.m3u8` already *is* the record of those Tracks; reading it back is cheaper and keeps this feature off the fragile path.
- **Version the file on a name clash (`List (2).m3u8`)** — rejected: it accumulates stale playlists pointing at moved/removed files; the user's intent is one current list per grouping.
- **Group by folder instead of a playlist file** — rejected: a Track in two monthly playlists needs two copies on disk, and the global download-archive skips the second — a plain list pointing at one file is what a library actually wants.

## Consequences

- The `.m3u8` writer is a provider **seam** the engine drives (like the Review queue), not core pipeline logic — a future web adapter would present the grouping differently and can inject its own writer or none. Consistent with ADR-0001.
- The engine writes the playlist only when the Downloader reports a `playlist_title` (set solely on a real expansion), reusing the ordered `tracks`/`results` it already has; each Track now carries its `duration` for `#EXTINF`.
- Merging reads the prior file each run — cheap, and it self-heals dead pointers by dropping entries whose file is gone.
- Paths are written relative to the playlist file's own folder and in forward slashes, so moving the folder (or reading it on another platform) doesn't break the list.
