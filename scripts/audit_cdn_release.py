"""Audit immutable Actions delivery and public bytes without rebuilding or uploading."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from check_publication import api, check_source, verify_bundle, verify_cdn, verify_index

REPOSITORY = "alpininsight/ais-webmcp"
REQUIRED_JOBS = {"source", "build", "pypi-verified", "cdn / Static Assets", "cdn / CDN Upload"}


def producer(run_id, attempt, artifact_id, version):
    """Require the exact completed main publisher, not merely a successful artifact."""
    if any(type(value) is not int or value < 1 for value in (run_id, attempt, artifact_id)):
        raise ValueError("producer run, attempt and artifact IDs must be positive integers")
    if version == "0.0.0" or not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version
    ):
        raise ValueError("audit requires a final release version")
    run = api(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    revision = run.get("head_sha", "")
    if not (
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("event") == "workflow_dispatch"
        and run.get("path") == ".github/workflows/release.yml"
        and run.get("head_branch") == "main"
        and re.fullmatch(r"[0-9a-f]{40}", revision)
        and (run.get("repository") or {}).get("full_name") == REPOSITORY
        and (run.get("head_repository") or {}).get("full_name") == REPOSITORY
        and run.get("status") == "completed"
        and run.get("conclusion") in {"success", "failure"}
    ):
        raise ValueError("producer must be the exact completed main release run and attempt")
    tag = api(f"repos/{REPOSITORY}/git/ref/tags/v{version}")
    target = tag.get("object", {})
    if target.get("type") == "tag":
        target = api(f"repos/{REPOSITORY}/git/tags/{target['sha']}").get("object", {})
    if target.get("type") != "commit" or target.get("sha") != revision:
        raise ValueError("release tag must identify the producer source")
    check_source(REPOSITORY, revision, require_merged_pr=True)
    jobs = api(f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
    rows = jobs.get("jobs", [])
    if type(jobs.get("total_count")) is not int or jobs["total_count"] != len(rows):
        raise ValueError("producer jobs must fit one complete verified page")
    for name in REQUIRED_JOBS | {"cdn-verified"}:
        matching = [job for job in rows if job.get("name") == name]
        if len(matching) != 1:
            raise ValueError(f"producer requires exactly one {name} job")
        job = matching[0]
        allowed = {"success", "failure"} if name == "cdn-verified" else {"success"}
        if not (
            job.get("run_id") == run_id
            and job.get("run_attempt") == attempt
            and job.get("head_sha") == revision
            and job.get("status") == "completed"
            and job.get("conclusion") in allowed
        ):
            raise ValueError(f"producer {name} job lacks exact-attempt publication evidence")
    # Only the readback job may have failed; an unrelated failed job is not accepted.
    if any(
        job.get("conclusion") not in {"success", "skipped"} and job.get("name") != "cdn-verified"
        for job in rows
    ):
        raise ValueError("producer has an unrelated failed job")
    artifact = api(f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}")
    owner = artifact.get("workflow_run") or {}
    digest = artifact.get("digest", "")
    if not (
        artifact.get("id") == artifact_id
        and artifact.get("name") == f"webmcp-delivery-{revision}"
        and artifact.get("expired") is False
        and owner.get("id") == run_id
        and owner.get("head_branch") == "main"
        and owner.get("head_sha") == revision
        and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    ):
        raise ValueError("delivery artifact must belong to the exact source publisher")
    # Artifact metadata has no attempt field. Bind creation to this attempt's
    # successful build interval rather than accepting an artifact from a rerun.
    build = next(job for job in rows if job["name"] == "build")
    try:
        created = datetime.fromisoformat(artifact["created_at"])
        started = datetime.fromisoformat(build["started_at"])
        completed = datetime.fromisoformat(build["completed_at"])
        if not started <= created <= completed:
            raise ValueError("artifact was not created by this producer build attempt")
    except (KeyError, TypeError) as error:
        raise ValueError("artifact requires complete producer build timestamps") from error
    return {
        "repository": REPOSITORY,
        "source_sha": revision,
        "version": version,
        "producer_run_id": run_id,
        "producer_attempt": attempt,
        "artifact_id": artifact_id,
        "artifact_digest": digest,
        "producer_conclusion": run["conclusion"],
    }


def download_delivery(evidence, bundle):
    """Check the immutable archive digest before extracting a closed file inventory."""
    archive = subprocess.check_output(
        ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{evidence['artifact_id']}/zip"]
    )
    if "sha256:" + hashlib.sha256(archive).hexdigest() != evidence["artifact_digest"]:
        raise ValueError("delivery archive digest mismatch")
    if bundle.exists():
        raise ValueError("audit requires a fresh bundle directory")
    version = evidence["version"]
    expected = {
        "cdn/register.js",
        "cdn/webmcp-manifest.schema.json",
        "cdn/inventory.json",
        f"dist/ais_webmcp-{version}-py3-none-any.whl",
        f"dist/ais_webmcp-{version}.tar.gz",
    }
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        files = [entry for entry in zipped.infolist() if not entry.is_dir()]
        if len(files) != len(expected) or {entry.filename for entry in files} != expected:
            raise ValueError("delivery archive must contain exactly the release inventory")
        for entry in files:
            if entry.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("delivery archive symlinks rejected")
        for entry in files:
            target = bundle / entry.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zipped.read(entry))


def audit(run_id, attempt, artifact_id, version, bundle):
    evidence = producer(run_id, attempt, artifact_id, version)
    download_delivery(evidence, bundle)
    verify_bundle(bundle, evidence["source_sha"], version)
    verify_index(bundle, version)
    evidence["objects"] = verify_cdn(bundle, version)
    evidence["audit_kind"] = "read-only-existing-delivery"
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-run-id", type=int, required=True)
    parser.add_argument("--producer-attempt", type=int, required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        args.producer_run_id,
        args.producer_attempt,
        args.artifact_id,
        args.version,
        args.bundle,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
