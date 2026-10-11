"""Read-only release gates; PyPI uploads run in the private per-package publishers.

The GitHub release and the CDN need the reviewed main source; the CDN also
needs its own PyPI project to carry exactly this reproducible build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from email.parser import Parser
from pathlib import Path


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def check_source(repository, revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("source must be a full commit SHA")
    branch = api(f"repos/{repository}/branches/main")
    if not branch["protected"] or branch["commit"]["sha"] != revision:
        raise ValueError("source must still be protected main head")
    checks = api(f"repos/{repository}/commits/{revision}/check-runs?per_page=100")["check_runs"]
    gates = sorted((c for c in checks if c["name"] == "WebMCP Quality Gate"), key=lambda c: c["id"])
    if not gates or gates[-1]["conclusion"] != "success":
        raise ValueError("latest exact-source WebMCP Quality Gate must succeed")
    approved = False
    for pull in api(f"repos/{repository}/commits/{revision}/pulls?per_page=100"):
        if not pull.get("merged_at") or pull["base"]["ref"] != "main":
            continue
        reviews = api(f"repos/{repository}/pulls/{pull['number']}/reviews?per_page=100")
        latest = {}
        for review in reviews:
            if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                latest[review["user"]["login"]] = review
        approved |= any(
            r["state"] == "APPROVED"
            and r["commit_id"] == pull["head"]["sha"]
            and user != pull["user"]["login"]
            for user, r in latest.items()
        )
    if not approved:
        raise ValueError("merged main promotion requires independent approval on its exact PR head")


def verify_bundle(bundle, revision, version):
    inventory = json.loads((bundle / "cdn/inventory.json").read_text())
    if (
        inventory["source_sha"] != revision
        or inventory["version"] != version
        or inventory["source_dirty"]
    ):
        raise ValueError("artifact provenance mismatch")
    expected = set()
    for entry in inventory["files"]:
        relative = Path(entry["path"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parts[0] not in {"dist", "cdn"}
        ):
            raise ValueError("invalid inventory path")
        path = bundle / relative
        if path.is_symlink():
            raise ValueError("artifact symlink rejected")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["size"]:
            raise ValueError("artifact checksum mismatch")
        if relative.parts[0] == "dist":
            expected.add(relative.name)
    files = [p for p in (bundle / "dist").iterdir() if p.name != ".gitignore"]
    if {p.name for p in files} != expected or len(files) != 2:
        raise ValueError("package inventory must contain exactly two artifacts")
    identities = []
    for path in files:
        if path.name.endswith(".whl"):
            with zipfile.ZipFile(path) as archive:
                metadata = archive.read(
                    next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
                )
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path) as archive:
                members = [
                    m
                    for m in archive.getmembers()
                    if m.name.count("/") == 1 and m.name.endswith("/PKG-INFO")
                ]
                if len(members) != 1:
                    raise ValueError("sdist metadata missing or ambiguous")
                metadata = archive.extractfile(members[0]).read()
        else:
            raise ValueError("unexpected package artifact")
        parsed = Parser().parsestr(metadata.decode())
        identities.append((parsed["Name"], parsed["Version"]))
    if sorted(identities) != sorted(
        [(name, version) for name in ("ais-webmcp",) for _ in range(2)]
    ):
        raise ValueError("package names or versions do not match the delivery")


PROJECTS = ("ais-webmcp",)
CDN_ROOT = "https://cdn.alpininsight.ai/ais-webmcp"


def verify_cdn(bundle, version):
    """Read all canonical objects in full; an edge challenge is a failed gate.

    This supplements the central uploader's exhaustive R2 check and sampled
    public header probe. It neither uploads nor bypasses the public edge.
    """
    if (
        not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version)
        or version == "0.0.0"
    ):
        raise ValueError("CDN verification requires a final nonzero release version")
    inventory = json.loads((bundle / "cdn/inventory.json").read_text())
    if inventory["version"] != version or inventory["cdn_prefix"] != "ais-webmcp":
        raise ValueError("CDN namespace or version mismatch")
    paths = {entry["path"] for entry in inventory["files"] if entry["path"].startswith("cdn/")}
    if paths != {"cdn/register.js", "cdn/webmcp-manifest.schema.json"}:
        raise ValueError("CDN inventory must contain both runtime resources")
    paths.add("cdn/inventory.json")
    origin = "https://insight-ui.com"
    report = []
    # One shared budget, including a 60-second margin beyond the mutable TTL.
    mutable_deadline = time.monotonic() + 360
    for alias in (f"v{version}", "main", "latest"):
        immutable = alias.startswith("v")
        for relative in sorted(paths):
            path = bundle / relative
            if path.is_symlink():
                raise ValueError("CDN artifact symlink rejected")
            expected = path.read_bytes()
            url = f"{CDN_ROOT}/{alias}/{path.name}"
            while True:
                try:
                    report.append(_verify_cdn_object(url, path, expected, immutable, origin))
                    break
                except ValueError:
                    # Mutable aliases can still serve the previous release for the
                    # uploader's entire 300-second TTL. Retry canonical URLs only;
                    # immutable defects and HTTP challenges fail immediately.
                    remaining = mutable_deadline - time.monotonic()
                    if immutable or remaining <= 0:
                        raise
                    time.sleep(min(20, remaining))
    return report


def _verify_cdn_object(url, path, expected, immutable, origin):
    request = urllib.request.Request(url, headers={"Origin": origin})
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError(f"canonical CDN GET failed: {url}")
        data = response.read(len(expected) + 1)
        content_type = response.headers.get_content_type()
        allowed_types = (
            {"application/javascript", "text/javascript"}
            if path.suffix == ".js"
            else {"application/json"}
        )
        cache = response.headers.get("Cache-Control", "")
        directives = [part.strip().lower() for part in cache.split(",")]
        max_age = "max-age=31536000" if immutable else "max-age=300"
        if (
            "public" not in directives
            or directives.count(max_age) != 1
            or sum(part.startswith("max-age=") for part in directives) != 1
            or any(
                part.split("=", 1)[0] in {"private", "no-cache", "no-store"} for part in directives
            )
            or ("immutable" in directives) != immutable
        ):
            raise ValueError(f"CDN cache policy mismatch: {url}")
        if content_type not in allowed_types:
            raise ValueError(f"CDN Content-Type mismatch: {url}")
        cors_values = response.headers.get_all("Access-Control-Allow-Origin", [])
        if len(cors_values) != 1 or cors_values[0] not in {"*", origin}:
            raise ValueError(f"CDN CORS mismatch: {url}")
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != len(expected) or digest != hashlib.sha256(expected).hexdigest():
        raise ValueError(f"CDN public bytes mismatch: {url}")
    cors = cors_values[0]
    return {
        "url": url,
        "size": len(data),
        "sha256": digest,
        "content_type": content_type,
        "cache_control": cache,
        "cors": cors,
    }


def project_files(bundle, name):
    """Exactly one wheel and one sdist of one project from the verified bundle."""
    prefix = name.replace("-", "_") + "-"
    files = sorted(p for p in (bundle / "dist").iterdir() if p.name.startswith(prefix))
    if len(files) != 2 or {p.name.endswith(".whl") for p in files} != {True, False}:
        raise ValueError("project must have exactly one wheel and one sdist")
    return files


def verify_index(bundle, version, projects=PROJECTS):
    """Public registry readback of the exact artifact checksums per project."""
    for name in projects:
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{name}/{version}/json", timeout=20
        ) as response:
            data = json.load(response)
        remote = {x["filename"]: x["digests"]["sha256"] for x in data["urls"]}
        local = {
            file.name: hashlib.sha256(file.read_bytes()).hexdigest()
            for file in project_files(bundle, name)
        }
        if remote != local:
            raise ValueError("registry checksum mismatch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("source", "bundle", "index", "cdn"))
    parser.add_argument("--repository")
    parser.add_argument("--sha")
    parser.add_argument("--version")
    parser.add_argument("--bundle", type=Path, default=Path("bundle"))
    parser.add_argument("--project", choices=PROJECTS)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.command == "source":
        check_source(args.repository, args.sha)
    elif args.command == "bundle":
        verify_bundle(args.bundle, args.sha, args.version)
    elif args.command == "cdn":
        report = verify_cdn(args.bundle, args.version)
        if args.report:
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
    else:
        projects = (args.project,) if args.project else PROJECTS
        for attempt in range(15):
            try:
                verify_index(args.bundle, args.version, projects)
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 14:
                    raise
                time.sleep(20)
