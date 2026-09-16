# The web adapter is a second thin adapter over the engine

**Status: Accepted (2026-08-30).** The web UI (`python -m muzik.web`) is what ADR-0001 promised: a sibling adapter beside the CLI, over the unchanged engine. It adds transport — HTTP routes, SSE streaming, a background run thread — and no pipeline knowledge of its own. Provider assembly is shared with the CLI through `muzik.wiring`; review decisions go through the engine's own `clear_review_queue`.

## The problem

The tool must be usable from other devices (ADR-0001's stated reason for the engine/adapter split). A web adapter raises four questions the CLI never had to answer: where provider wiring lives once two adapters need it; how a browser applies a Review decision without a second implementation of queue semantics; whether concurrent runs are allowed; and how batch progress reaches a page that isn't a terminal.

## The decisions

### Shared wiring, one module

The CLI's provider assembly — rate limits, key-degradation to disabled tiers, format resolution — moved to `muzik.wiring`, and both adapters call the same builders. That assembly is *policy* (how hard Muzik may hit Shazam, what happens without an API key), and policy must be one decision, not two copies that drift. The CLI re-exports the builders under its old private names so its surface and tests are unchanged.

### Review decisions through a one-shot prompter

The engine already owns queue-clearing: `clear_review_queue` drives a `ReviewPrompter` seam, applies each decision, and rewrites the queue with the survivors. The web adapter applies *one* decision by running that same pass with a one-shot prompter — answer for the entry at the requested index (position *and* `source_url` must match, so a stale index from an old listing 409s instead of clearing the wrong Track), skip for everything else. A skip leaves an entry untouched, so the rest of the queue survives verbatim.

Rejected alternative: queue-mutation endpoints that edit the JSONL directly. That would duplicate the survivor/rewrite semantics — and the accept/manual/hint tagging paths behind them — in a second place, which is exactly the drift the prompter seam exists to prevent.

### One active run

The manager holds a single run and 409s a second, and a Review decision is refused (409) while a run is active. Not a simplification but an invariant: the Review queue's O(1) append is safe only because it has one writer (the engine's drain loop, #64), and the download manifest and `.m3u8` merge assume the same. The CLI got this for free by being one sequential process; the web adapter must enforce it. This is a personal tool — the concurrency worth having is *within* a batch (engine's worker pool), not between batches.

### Progress over SSE, through the engine's seams

Server-sent events, not WebSockets: the stream is strictly server→client, SSE is plain HTTP (fits `EventSource`, proxies, and a one-process server), and the client's only upstream messages are ordinary POSTs. Events come from the two seams the engine/Downloader expose — `run(on_result=…)` per finished Track, the Downloader's `on_event` per download tick — buffered into a per-subscriber queue so a slow reader never stalls the run. A subscriber gets a full `snapshot` first, then deltas; the snapshot and the subscription are taken under one lock, so no event between them can be missed. `on_result` fires after the Track's Review enqueue and playlist flush, so a `track` event only ever reports an outcome already on disk — a refresh after a crash shows the same truth the stream did.

## Consequences

- The engine still compiles with no knowledge of either adapter; the web adapter imports `engine`, `wiring`, `settings`, and domain types — nothing from `muzik.real` directly.
- `--demo` swaps the builder for seeded fakes (`web/demo.py`) and serves the full UI offline — the same factory, different injection, per ADR-0001.
- The API's wire shapes are pinned by contract in `web/wire.py`; the SPA is built against them, so they change there first or not at all.
- A run started from the web has no CLI-visible progress and vice versa — the two adapters share the engine and its on-disk state (manifest, queue, playlist), not each other's processes. Accepted: one tool, one operator, one process at a time.
