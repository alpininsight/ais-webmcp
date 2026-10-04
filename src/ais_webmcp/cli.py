"""Django-free WebMCP command line.

``ais-webmcp`` and ``python -m ais_webmcp`` import this module only.
The console script name is ``ais-webmcp`` (not ``webmcp``). This distribution
does not depend on Django.

This build implements ``validate``, ``init``, and ``list``. ``doctor`` stays later.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ais_webmcp.listing import list_manifests
from ais_webmcp.scaffold import init_manifest
from webmcp_manifest.validate import exit_code, render, validate_path


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the ``ais-webmcp`` console script."""
    parser = argparse.ArgumentParser(
        prog="ais-webmcp",
        description=(
            "Dev/CI client for WebMCP manifests. No live page, no browser control. "
            "This build implements validate, init, and list, and does not import Django."
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

    init = sub.add_parser(
        "init",
        help="Write a starter manifest.yaml (scaffold only; pass --static for page stubs)",
    )
    init.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help=(
            "Manifest file or directory (default: ./manifest.yaml). "
            "A directory receives manifest.yaml. Suffix .json writes JSON."
        ),
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Replace existing scaffold files and print a diff summary.",
    )
    init.add_argument(
        "--static",
        action="store_true",
        help="Also write index.html and webmcp.js stubs next to the manifest.",
    )

    listing = sub.add_parser(
        "list",
        help="Print tools from a manifest (read-only; does not register them)",
    )
    listing.add_argument(
        "manifests",
        nargs="+",
        type=Path,
        help="Manifest paths (.json, .yaml, or .yml).",
    )
    listing.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="text (default) or json. enabled is null in JSON when the key is omitted.",
    )
    listing.add_argument(
        "--allow-profile",
        action="append",
        default=None,
        help="Additional profile name to accept (repeatable). Built-ins always allowed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    ``validate`` and ``list`` return 0 when every manifest is valid, 1 when a
    manifest is invalid, and 2 when a file cannot be read or parsed.
    ``init`` returns 0 when the scaffold is written, 1 when it refuses to
    overwrite, and 2 on a bad path or write error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        extra = tuple(args.allow_profile or ())
        results = [validate_path(path, extra_profiles=extra) for path in args.manifests]
        sys.stdout.write(render(results, args.format))
        return exit_code(results)
    if args.command == "list":
        extra = tuple(args.allow_profile or ())
        text, code = list_manifests(list(args.manifests), fmt=args.format, extra_profiles=extra)
        sys.stdout.write(text)
        return code
    if args.command == "init":
        result = init_manifest(args.output, force=args.force, static=args.static)
        sys.stdout.write(result.report)
        return result.exit_code
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
