"""Read-only checks for source CI, local bundles, and public registry checksums."""

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
from pathlib import Path, PurePosixPath


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def check_source(repository, revision, *, require_merged_pr=False):
    """Reuse the latest exact main push evidence, never another event or attempt."""
    if repository != "alpininsight/ais-webmcp":
        raise ValueError("source repository does not match this package")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("source must be a full commit SHA")
    branch = api(f"repos/{repository}/branches/main")
    if not branch["protected"] or branch["commit"]["sha"] != revision:
        raise ValueError("source must still be protected main head")
    runs = api(
        f"repos/{repository}/actions/workflows/ci.yml/runs"
        f"?branch=main&event=push&head_sha={revision}&per_page=1"
    ).get("workflow_runs", [])
    if not runs:
        raise ValueError("no CI main push run for this exact source SHA")
    # Do not filter by success: a newer failure/in-flight attempt invalidates it.
    run = runs[0]
    if not (
        run.get("head_sha") == revision
        and run.get("head_branch") == "main"
        and run.get("event") == "push"
        and run.get("path") == ".github/workflows/ci.yml"
        and (run.get("repository") or {}).get("full_name") == repository
        and (run.get("head_repository") or {}).get("full_name") == repository
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and type(run.get("id")) is int
        and run["id"] > 0
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] > 0
    ):
        raise ValueError("latest exact-SHA main push CI must have completed successfully")
    jobs = api(f"repos/{repository}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")
    count = jobs.get("total_count") if isinstance(jobs, dict) else None
    rows = jobs.get("jobs") if isinstance(jobs, dict) else None
    if (
        type(count) is not int
        or not 0 <= count <= 100
        or not isinstance(rows, list)
        or len(rows) != count
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise ValueError("CI job inventory must fit one complete verified page")
    gates = [j for j in rows if j.get("name") == "WebMCP Quality Gate"]
    if len(gates) != 1:
        raise ValueError("CI needs exactly one WebMCP Quality Gate job")
    gate = gates[0]
    if not (
        gate.get("head_sha") == revision
        and gate.get("run_id") == run["id"]
        and gate.get("run_attempt") == run["run_attempt"]
        and gate.get("status") == "completed"
        and gate.get("conclusion") == "success"
        and type(gate.get("id")) is int
        and gate["id"] > 0
    ):
        raise ValueError("exact-SHA WebMCP Quality Gate must succeed for the latest attempt")
    if require_merged_pr:
        require_main_promotion(repository, revision)
    return {
        "source_ci_run": run["id"],
        "source_ci_attempt": run["run_attempt"],
        "source_quality_job": gate["id"],
    }


def require_main_promotion(repository, revision):
    """Require the exact source SHA to come from a merged promotion into main."""
    for page in range(1, 21):
        pulls = api(f"repos/{repository}/commits/{revision}/pulls?per_page=100&page={page}")
        if not isinstance(pulls, list):
            raise ValueError("invalid source PR metadata")
        for summary in pulls:
            number = summary.get("number")
            if type(number) is not int or number < 1:
                raise ValueError("invalid source PR number")
            pr = api(f"repos/{repository}/pulls/{number}")
            if (
                pr.get("number") == number
                and pr.get("merged") is True
                and pr.get("state") == "closed"
                and pr.get("draft") is False
                and bool(pr.get("merged_at"))
                and pr.get("merge_commit_sha") == revision
                and (pr.get("base") or {}).get("ref") == "main"
                and ((pr.get("base") or {}).get("repo") or {}).get("full_name") == repository
            ):
                return
        if len(pulls) < 100:
            break
    raise ValueError("exact source SHA must come from a merged PR into main")


def _artifact_path(bundle, relative):
    """Reject symlinks at the bundle root and every inventory path component."""
    # Delivery inventories use POSIX separators even on Windows. Validate that
    # lexical contract before joining the components to the native bundle path.
    relative = PurePosixPath(relative)
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in str(relative)
        or relative.parts[0] not in {"dist", "cdn"}
    ):
        raise ValueError("invalid inventory path")
    path = bundle
    if path.is_symlink():
        raise ValueError("artifact symlink rejected")
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("artifact symlink rejected")
    return path


def verify_bundle(bundle, revision, version):
    inventory = json.loads(_artifact_path(bundle, "cdn/inventory.json").read_text())
    if (
        inventory["source_sha"] != revision
        or inventory["version"] != version
        or inventory["source_dirty"]
    ):
        raise ValueError("artifact provenance mismatch")
    expected = set()
    recorded = set()
    for entry in inventory["files"]:
        relative = PurePosixPath(entry["path"])
        path = _artifact_path(bundle, relative)
        canonical = relative.as_posix()
        if canonical in recorded or canonical != entry["path"]:
            raise ValueError("duplicate or non-canonical inventory path")
        recorded.add(canonical)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["size"]:
            raise ValueError("artifact checksum mismatch")
        if relative.parts[0] == "dist":
            expected.add(relative.name)
    actual = set()
    for directory in ("dist", "cdn"):
        root = _artifact_path(bundle, directory)
        for path in root.rglob("*"):
            relative = path.relative_to(bundle)
            _artifact_path(bundle, relative.as_posix())
            if path.is_file() and relative.as_posix() != "dist/.gitignore":
                actual.add(relative.as_posix())
    if actual != recorded | {"cdn/inventory.json"}:
        raise ValueError("artifact inventory must match all delivered files")
    files = [p for p in (bundle / "dist").iterdir() if p.name != ".gitignore"]
    if {p.name for p in files} != expected or len(files) != 2:
        raise ValueError("package inventory must contain exactly two artifacts")
    if (
        sum(p.name.endswith(".whl") for p in files) != 1
        or sum(p.name.endswith(".tar.gz") for p in files) != 1
    ):
        raise ValueError("package inventory must contain exactly one wheel and one sdist")
    identities = []
    for path in files:
        if path.name.endswith(".whl"):
            with zipfile.ZipFile(path) as archive:
                members = [
                    entry
                    for entry in archive.infolist()
                    if entry.filename.endswith(".dist-info/METADATA")
                ]
                if (
                    len(members) != 1
                    or members[0].filename != f"ais_webmcp-{version}.dist-info/METADATA"
                ):
                    raise ValueError("wheel metadata missing, ambiguous or non-canonical")
                metadata = archive.read(members[0])
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
    parser.add_argument("command", choices=("source", "bundle", "index"))
    parser.add_argument("--repository")
    parser.add_argument("--require-merged-pr", action="store_true")
    parser.add_argument("--sha")
    parser.add_argument("--version")
    parser.add_argument("--bundle", type=Path, default=Path("bundle"))
    parser.add_argument("--project", choices=PROJECTS)
    args = parser.parse_args()
    if args.command == "source":
        print(
            json.dumps(
                check_source(args.repository, args.sha, require_merged_pr=args.require_merged_pr)
            )
        )
    elif args.command == "bundle":
        verify_bundle(args.bundle, args.sha, args.version)
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
