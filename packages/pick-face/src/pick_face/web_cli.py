"""pick-face-web CLI — `docs/06 §1.2` + `docs/01 §1.1`.

Subcommands:

- ``init``    — first-run setup: create ``~/.pick-face/`` layout,
                write default ``config.toml``, optionally add a scan
                path. Idempotent.
- ``serve``   — start the FastAPI app via uvicorn. Binds to the
                host/port from config.toml.
- ``migrate`` — reserved for v2.x → v3.x index migration. In M6 it
                just ensures the schema is current (calls
                ``worker.scan_worker.ensure_schema``).

The CLI uses stdlib :mod:`argparse` rather than ``typer`` — the
``pick-face`` (v2.x) CLI is the public surface and we don't want to
drag ``typer`` into the v3 Web extra.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pick_face.service.config_service import write_default_config
from pick_face.service.paths import ENV_VAR, get_layout, resolve_root
from pick_face.worker.scan_worker import ensure_schema


def cmd_init(args: argparse.Namespace) -> int:
    """Create the app layout + default config; optionally add a scan path."""
    if args.root:
        root = resolve_root(args.root)
    else:
        root = resolve_root()
    layout = get_layout(data_dir=root)
    config_path = write_default_config(layout, scan_path=args.add_path)
    print(f"app root:   {layout.root}")
    print(f"config:     {config_path}")
    print(f"data dir:   {layout.data_dir}")
    print(f"cache dir:  {layout.cache_dir}")
    if args.add_path is None:
        print("hint: run `pick-face-web init --add-path /your/photos` to whitelist a scan root")
    else:
        from pick_face.service.config_service import ConfigService, PathValidationError

        try:
            sp = ConfigService(layout).add_path(args.add_path, notes="initial path")
            print(f"whitelisted: {sp.path}  (id={sp.id})")
        except PathValidationError as exc:
            print(f"warning: could not whitelist {args.add_path}: {exc.message} ({exc.code})")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start uvicorn serving the FastAPI app."""
    import uvicorn

    layout = get_layout()
    host = args.host or "127.0.0.1"
    port = args.port or 8000
    print(f"pick-face Web service: http://{host}:{port}")
    print(f"app root: {layout.root}")
    uvicorn.run(
        "pick_face.api.app:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """M6 stub — ensure the v2.x SQLite schema is current.

    Full v2 → v3 data migration lands in a later milestone
    (`docs/06 §3.1`). For M6 we just make sure the v2.x tables exist
    so the worker can start writing immediately.
    """
    layout = get_layout()
    ensure_schema(layout.db_path)
    print(f"schema ensured at {layout.db_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pick-face-web",
        description="pick-face v3 Web service CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Shared ``--root`` arg registered on every subcommand so argparse
    # routes it correctly regardless of position.
    def _add_root(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--root",
            help=f"App data root (overrides ${ENV_VAR} and default ~/.pick-face)",
        )

    p_init = sub.add_parser("init", help="initialize app root + config")
    _add_root(p_init)
    p_init.add_argument(
        "--add-path",
        type=Path,
        help="also whitelist this scan path (must exist + be a directory)",
    )
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="start the FastAPI app via uvicorn")
    _add_root(p_serve)
    p_serve.add_argument("--host", help="bind host (default 127.0.0.1)")
    p_serve.add_argument("--port", type=int, help="bind port (default 8000)")
    p_serve.add_argument("--reload", action="store_true", help="auto-reload on file change")
    p_serve.add_argument("--log-level", default="info", help="uvicorn log level")
    p_serve.set_defaults(func=cmd_serve)

    p_mig = sub.add_parser("migrate", help="ensure v2.x schema is current (M6 stub)")
    _add_root(p_mig)
    p_mig.set_defaults(func=cmd_migrate)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
