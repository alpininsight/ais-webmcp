"""CI gate for committed WebMCP manifest fixtures.

Runs the Django-free ``ais-webmcp`` console script (or ``python -m insight_ui_webmcp``).
This file must not import Django or the package: the child process is the check.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VALID = (
    ROOT / "tests" / "fixtures" / "manifests" / "valid" / "webpage.json",
    ROOT / "tests" / "fixtures" / "manifests" / "valid" / "webpage.yaml",
)
INVALID_DIR = ROOT / "tests" / "fixtures" / "manifests" / "invalid"
REQUIRED_INVALID = {
    "duplicate-id.json",
    "consequential-without-enable.json",
    "missing-input-schema.json",
    "unknown-annotation.json",
    "ambiguous-schema-keys.json",
    "unknown-profile.json",
    "input-schema-not-object.json",
    "missing-name.json",
    "missing-description.json",
}


def _argv(manifest: Path) -> list[str]:
    script = Path(sys.executable).with_name("ais-webmcp")
    if script.is_file():
        return [str(script), "validate", str(manifest)]
    return [sys.executable, "-m", "insight_ui_webmcp", "validate", str(manifest)]


def _run(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _argv(manifest),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    """Return 0 when valid fixtures pass, invalid fixtures fail, and newsletter stays off."""
    failed = False
    names = {path.name for path in INVALID_DIR.glob("*.json")}
    missing = REQUIRED_INVALID - names
    if missing:
        print(f"missing invalid fixtures: {sorted(missing)}", file=sys.stderr)
        failed = True
    if not names:
        print("no invalid fixtures found", file=sys.stderr)
        failed = True

    documents = []
    for path in VALID:
        if not path.is_file():
            print(f"missing valid fixture: {path}", file=sys.stderr)
            failed = True
            continue
        proc = _run(path)
        if proc.returncode != 0:
            print(f"expected exit 0 for {path.name}\n{proc.stdout}\n{proc.stderr}", file=sys.stderr)
            failed = True
        else:
            print(f"ok {path.name}")
        if path.suffix == ".json":
            documents.append(json.loads(path.read_text(encoding="utf-8")))
        else:
            documents.append(yaml.safe_load(path.read_text(encoding="utf-8")))

    if len(documents) == 2 and documents[0] != documents[1]:
        print("webpage.json and webpage.yaml are not the same manifest", file=sys.stderr)
        failed = True

    if documents:
        tools = documents[0].get("tools", [])
        subscribe = [tool for tool in tools if tool.get("id") == "subscribe_newsletter"]
        if len(subscribe) != 1 or subscribe[0].get("consequential") is not True:
            print("subscribe_newsletter must stay consequential", file=sys.stderr)
            failed = True
        elif subscribe[0].get("enabled") is not False:
            print("subscribe_newsletter must ship enabled false (#3)", file=sys.stderr)
            failed = True
        if any(
            tool.get("id", "").startswith("subscribe_") and tool.get("enabled") is True
            for tool in tools
        ):
            print("subscribe_* must not be enabled in the valid fixture", file=sys.stderr)
            failed = True

    for path in sorted(INVALID_DIR.glob("*")):
        if not path.is_file():
            continue
        proc = _run(path)
        if proc.returncode == 0:
            print(f"expected non-zero exit for {path.name}\n{proc.stdout}", file=sys.stderr)
            failed = True
        else:
            print(f"rejected {path.name} (exit {proc.returncode})")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
