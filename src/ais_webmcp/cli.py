"""Django-free WebMCP command line.

``ais-webmcp`` and ``python -m insight_ui_webmcp`` import this module only.
The console script name is ``ais-webmcp``. Its package does not require Django.

All operations use local files; doctor reports configuration evidence only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ais_webmcp.listing import list_manifests
from ais_webmcp.scaffold import init_manifest
from ais_webmcp.validate import exit_code, render, validate_path


def profile_argument(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("profile must be a non-empty string")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the ``ais-webmcp`` console script."""
    parser = argparse.ArgumentParser(
        prog="ais-webmcp",
        description=(
            "Dev/CI client for WebMCP manifests. No live page, no browser control. "
            "Create, inspect, diagnose, compare and export validated local manifests."
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
        type=profile_argument,
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
        type=profile_argument,
        default=None,
        help="Additional profile name to accept (repeatable). Built-ins always allowed.",
    )
    for command in ("doctor", "status"):
        diagnosis = sub.add_parser(
            command,
            help="Read-only local host checklist (manifest, CSP notes, redacted Origin Trial)",
        )
        diagnosis.add_argument(
            "manifest",
            help="Local manifest path. http and https URLs are refused.",
        )
        diagnosis.add_argument(
            "--html",
            help="Optional local HTML file. Remote URLs are refused.",
        )
        diagnosis.add_argument("--format", choices=("text", "json"), default="text")
        diagnosis.add_argument(
            "--tree",
            action="store_true",
            help="Print Atomic Design grouping: atom → molecule → organism (tool.group).",
        )
        diagnosis.add_argument("--allow-profile", action="append", type=profile_argument)
    diff = sub.add_parser("diff", help="Compare validated manifests; 1 means differences")
    diff.add_argument("left", type=Path)
    diff.add_argument("right", type=Path)
    diff.add_argument("--allow-profile", action="append", type=profile_argument)
    export = sub.add_parser(
        "export",
        help="Export a validated manifest, JSON tools list, or static snippet",
    )
    export.add_argument("source", type=Path)
    export.add_argument("--output", "-o", type=Path, required=True)
    export.add_argument(
        "--kind",
        choices=("manifest", "tools", "snippet"),
        default="manifest",
        help="manifest (canonical JSON/YAML), tools (JSON list), or snippet (HTML, no token).",
    )
    export.add_argument("--force", action="store_true")
    export.add_argument("--allow-profile", action="append", type=profile_argument)
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
    if args.command in {"doctor", "status", "diff", "export"}:
        import json

        from ais_webmcp.operations import diff_manifests, doctor, export_manifest

        extra = tuple(args.allow_profile or ())
        if args.command in {"doctor", "status"}:
            report, code = doctor(
                args.manifest,
                html=args.html,
                extra_profiles=extra,
                tree=args.tree,
            )
            if args.format == "json":
                sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
            else:
                from ais_webmcp.operations import format_atomic_tree

                lines = []
                for row in report["checks"]:
                    line = f"{row['check']}: {row['status']}"
                    if row.get("detail"):
                        line = f"{line} ({row['detail']})"
                    lines.append(line)
                body = "\n".join(lines) + "\n" + report["note"] + "\n"
                if report.get("tree"):
                    body = body + format_atomic_tree(report["tree"])
                sys.stdout.write(body)
            return code
        if args.command == "diff":
            report, code = diff_manifests(args.left, args.right, extra_profiles=extra)
        else:
            result = export_manifest(
                args.source,
                args.output,
                force=args.force,
                extra_profiles=extra,
                kind=args.kind,
            )
            report, code = result.report, result.exit_code
        sys.stdout.write(report)
        return code
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
