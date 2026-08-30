"""Entry point: ``python -m muzik.web`` serves the SPA and API on localhost.

A personal tool on a private interface by default (127.0.0.1) — binding wider
is the operator's explicit call (e.g. a tailnet address), not a default.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from muzik.web.app import create_app


def main() -> int:
    # Same env contract as the CLI: keys come from the environment / .env, and
    # the wiring notes print here — the server log is this adapter's terminal.
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="python -m muzik.web",
        description="Serve Muzik's web adapter (API + SPA) over the engine.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: localhost only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--out", type=Path, default=Path("downloads"), help="Output directory")
    parser.add_argument("--cookies", type=Path, default=None, help="Cookies file for age-restricted Sources")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Serve seeded fake providers (offline, instant) instead of the real pipeline",
    )
    args = parser.parse_args()

    if args.demo:
        from muzik.web.demo import build_demo

        # Demo state — files, queue, and the settings file — lives in a fresh
        # temp dir, so a demo can never touch the real library or settings.
        demo_dir = Path(tempfile.mkdtemp(prefix="muzik-demo-"))
        app = create_app(build_demo(demo_dir), demo_dir, settings_path=demo_dir / "settings.json")
        print(f"demo mode: state in {demo_dir}")
    else:
        from muzik.engine import Providers
        from muzik.settings import OutputFormat
        from muzik.wiring import build_downloader, build_providers

        def builder(
            fmt: OutputFormat,
            *,
            expand_playlist: bool = False,
            limit: int | None = None,
            on_event=None,
        ) -> Providers:
            downloader = build_downloader(
                args.out, args.cookies, fmt,
                expand_playlist=expand_playlist, limit=limit, on_event=on_event,
            )
            return build_providers(downloader, fmt, args.out)

        app = create_app(builder, args.out)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
