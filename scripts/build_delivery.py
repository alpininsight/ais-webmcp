"""Build the core distribution and an exact, hashable CDN inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import zipfile
from email.parser import Parser
from pathlib import Path


def build(version: str, output: Path):
    # Only a final MAJOR.MINOR.PATCH from GitVersion ships: no 0.0.0, no
    # PEP 440 pre/dev/post/local segments, no leading zeros or "v" prefix.
    if (
        not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version)
        or version == "0.0.0"
    ):
        raise ValueError("delivery requires an explicit nonzero GitVersion version")
    if output.exists() and any(output.iterdir()):
        raise ValueError("delivery output must be empty")
    epoch = subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "HEAD"], text=True
    ).strip()
    env = os.environ | {"SETUPTOOLS_SCM_PRETEND_VERSION": version, "SOURCE_DATE_EPOCH": epoch}
    dist = output / "dist"
    subprocess.run(["uv", "build", "--out-dir", str(dist.resolve())], env=env, check=True)
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1 or len(list(dist.glob("*.tar.gz"))) != 1:
        raise ValueError("expected one core wheel and one sdist")
    assets = output / "cdn"
    assets.mkdir()
    js_files = []
    schemas = []
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            metadata = Parser().parsestr(
                archive.read(
                    next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
                ).decode()
            )
            if metadata["Name"] != "ais-webmcp" or metadata["Version"] != version:
                raise ValueError("wheel metadata version drift")
            js_files.append(
                archive.read(next(n for n in archive.namelist() if n.endswith("/register.js")))
            )
            schemas.append(
                archive.read(
                    next(
                        n for n in archive.namelist() if n.endswith("/webmcp-manifest.schema.json")
                    )
                )
            )
    if not re.search(rf'version\s*:\s*"{re.escape(version)}"', js_files[0].decode()):
        raise ValueError("runtime version drift")
    (assets / "register.js").write_bytes(js_files[0])
    (assets / "webmcp-manifest.schema.json").write_bytes(schemas[0])
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    entries = [
        {
            "path": p.relative_to(output).as_posix(),
            "size": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted([*dist.glob("*.whl"), *dist.glob("*.tar.gz"), *assets.iterdir()])
    ]
    inventory = {
        "version": version,
        "source_sha": revision,
        "source_dirty": dirty,
        "cdn_prefix": "ais-webmcp",
        "files": entries,
    }
    (assets / "inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    return inventory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, default=Path("dist/delivery"))
    args = parser.parse_args()
    build(args.version, args.output)
