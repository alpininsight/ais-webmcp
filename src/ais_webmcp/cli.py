"""Django-free WebMCP command line.

``ais-webmcp validate`` and ``python -m insight_ui_webmcp validate`` import this
module only. The console script name is ``ais-webmcp`` (not ``webmcp``). It must not import Django (issue #15 tracks the install extra).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from insight_ui_webmcp.validate import exit_code, render, validate_path


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the ``ais-webmcp`` console script."""
    parser = argparse.ArgumentParser(
        prog="ais-webmcp",
        description=(
            "Dev/CI client for WebMCP manifests. No live page, no browser control. "
            "This build implements validate only and does not import Django."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser(
        "validate",
        help="Validate a WebMCP manifest (JSON or YAML) against the shared schema",
    )
    validate.add_argument(
        "manifests",
        nargs="+",
        type=Path,
        help="Manifest paths (.json, .yaml, or .yml).",
    )
    validate.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="text (default) or json.",
    )
    validate.add_argument(
        "--allow-profile",
        action="append",
        default=None,
        help="Additional profile name to accept (repeatable). Built-ins always allowed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns 0 valid, 1 invalid, 2 unreadable or unparsable."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "validate":
        parser.error(f"unknown command {args.command}")
    extra = tuple(args.allow_profile or ())
    results = [validate_path(path, extra_profiles=extra) for path in args.manifests]
    sys.stdout.write(render(results, args.format))
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
