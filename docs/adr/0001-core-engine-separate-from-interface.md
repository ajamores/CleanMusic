# Core engine separate from interface

The download → identify → tag logic lives in a standalone core engine (a plain library) that has no knowledge of how it is invoked. The CLI is a thin adapter over that engine; a future web/server interface will be a second adapter over the same engine.

Chosen because the tool must eventually be usable from other devices. Building the engine interface-agnostic now makes the web version a new adapter rather than a rewrite. The cost is more structure upfront than a single-file CLI script would need — accepted deliberately.
