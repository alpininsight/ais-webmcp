"""A failed public readback can be audited without trusting another producer or writing CDN."""

import copy
import hashlib
import importlib.util
import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
publication_spec = importlib.util.spec_from_file_location(
    "audit_publication", ROOT / "scripts/check_publication.py"
)
publication = importlib.util.module_from_spec(publication_spec)
publication_spec.loader.exec_module(publication)
spec = importlib.util.spec_from_file_location(
    "release_audit", ROOT / "scripts/audit_cdn_release.py"
)
audit = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"check_publication": publication}):
    spec.loader.exec_module(audit)
SHA = "a" * 40


@pytest.fixture
def producer(monkeypatch):
    state = {
        "run": {
            "id": 10,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "path": ".github/workflows/release.yml",
            "head_branch": "main",
            "head_sha": SHA,
            "repository": {"full_name": audit.REPOSITORY},
            "head_repository": {"full_name": audit.REPOSITORY},
            "status": "completed",
            "conclusion": "failure",
        },
        "tag": {"object": {"type": "commit", "sha": SHA}},
        "artifact": {
            "id": 20,
            "name": f"webmcp-delivery-{SHA}",
            "expired": False,
            "created_at": "2026-10-20T23:02:16Z",
            "digest": "sha256:" + "b" * 64,
            "workflow_run": {"id": 10, "head_branch": "main", "head_sha": SHA},
        },
        "jobs": [
            {
                "name": name,
                "run_id": 10,
                "run_attempt": 1,
                "head_sha": SHA,
                "status": "completed",
                "started_at": "2026-10-20T23:02:04Z",
                "completed_at": "2026-10-20T23:02:20Z",
                "conclusion": "failure" if name == "cdn-verified" else "success",
            }
            for name in sorted(audit.REQUIRED_JOBS | {"cdn-verified"})
        ],
        "source_checks": [],
    }

    def api(path):
        if path.endswith("/actions/runs/10"):
            return state["run"]
        if path.endswith("/git/ref/tags/v0.1.1"):
            return state["tag"]
        if path.endswith("/attempts/1/jobs?per_page=100"):
            return {"total_count": len(state["jobs"]), "jobs": state["jobs"]}
        if path.endswith("/actions/artifacts/20"):
            return state["artifact"]
        pytest.fail(f"unexpected API access: {path}")

    monkeypatch.setattr(audit, "api", api)
    monkeypatch.setattr(
        audit,
        "check_source",
        lambda repo, sha, **kwargs: state["source_checks"].append((repo, sha, kwargs)),
    )
    return state


def test_failed_readback_with_successful_upload_can_be_audited(producer):
    result = audit.producer(10, 1, 20, "0.1.1")
    assert result["source_sha"] == SHA
    assert result["producer_conclusion"] == "failure"
    assert producer["source_checks"] == [(audit.REPOSITORY, SHA, {"require_merged_pr": True})]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 11),
        ("run_attempt", 2),
        ("event", "pull_request"),
        ("path", ".github/workflows/cdn-develop.yml"),
        ("path", ".github/workflows/ci.yml"),
        ("path", ".github/workflows/ais-webmcp-release-assets.yml"),
        ("head_branch", "develop"),
        ("head_sha", "not-a-sha"),
        ("repository", {"full_name": "other/repository"}),
        ("head_repository", {"full_name": "other/repository"}),
        ("status", "in_progress"),
        ("conclusion", "cancelled"),
    ],
)
def test_wrong_or_unfinished_producer_rejected(producer, field, value):
    producer["run"][field] = value
    with pytest.raises(ValueError, match="completed main release"):
        audit.producer(10, 1, 20, "0.1.1")


def test_tag_drift_and_source_gate_failures_rejected(producer, monkeypatch):
    producer["tag"]["object"]["sha"] = "c" * 40
    with pytest.raises(ValueError, match="release tag"):
        audit.producer(10, 1, 20, "0.1.1")
    producer["tag"]["object"]["sha"] = SHA

    def fail_source(*args, **kwargs):
        raise ValueError("main is no longer protected or current")

    monkeypatch.setattr(audit, "check_source", fail_source)
    with pytest.raises(ValueError, match="main"):
        audit.producer(10, 1, 20, "0.1.1")


@pytest.mark.parametrize("name", sorted(audit.REQUIRED_JOBS))
@pytest.mark.parametrize("defect", ["failure", "skipped", "other-attempt", "duplicate"])
def test_every_required_upload_job_must_succeed_at_exact_attempt(producer, name, defect):
    job = next(job for job in producer["jobs"] if job["name"] == name)
    if defect == "duplicate":
        producer["jobs"].append(copy.deepcopy(job))
    elif defect == "other-attempt":
        job["run_attempt"] = 2
    else:
        job["conclusion"] = defect
    with pytest.raises(ValueError, match="producer"):
        audit.producer(10, 1, 20, "0.1.1")


@pytest.mark.parametrize(
    "change",
    [
        {"id": 21},
        {"name": "unrelated-delivery"},
        {"expired": True},
        {"created_at": "2026-10-20T22:00:00Z"},
        {"digest": ""},
        {"workflow_run": {"id": 11, "head_branch": "main", "head_sha": SHA}},
        {"workflow_run": {"id": 10, "head_branch": "develop", "head_sha": SHA}},
        {"workflow_run": {"id": 10, "head_branch": "main", "head_sha": "c" * 40}},
    ],
)
def test_wrong_or_expired_artifact_rejected(producer, change):
    producer["artifact"].update(change)
    with pytest.raises(ValueError, match="artifact"):
        audit.producer(10, 1, 20, "0.1.1")


def archive_bytes(extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in [
            "cdn/register.js",
            "cdn/webmcp-manifest.schema.json",
            "cdn/inventory.json",
            "dist/ais_webmcp-0.1.1-py3-none-any.whl",
            "dist/ais_webmcp-0.1.1.tar.gz",
        ]:
            archive.writestr(name, b"fixture")
        if extra:
            archive.writestr(extra, b"untrusted")
    return output.getvalue()


@pytest.mark.parametrize("extra", [None, "../outside", "cdn/unexpected.js"])
def test_archive_hash_and_closed_inventory_before_extraction(tmp_path, monkeypatch, extra):
    data = archive_bytes(extra)
    monkeypatch.setattr(audit.subprocess, "check_output", lambda cmd: data)
    evidence = {
        "artifact_id": 20,
        "version": "0.1.1",
        "artifact_digest": "sha256:" + hashlib.sha256(data).hexdigest(),
    }
    bundle = tmp_path / "bundle"
    if extra:
        with pytest.raises(ValueError, match="inventory"):
            audit.download_delivery(evidence, bundle)
        assert not bundle.exists()
        assert not (tmp_path / "outside").exists()
    else:
        audit.download_delivery(evidence, bundle)
        assert (bundle / "cdn/register.js").read_bytes() == b"fixture"
        with pytest.raises(ValueError, match="fresh"):
            audit.download_delivery(evidence, bundle)
    evidence["artifact_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="digest"):
        audit.download_delivery(evidence, tmp_path / "other")


def test_audit_pipeline_checks_provenance_and_pypi_before_public_cdn(
    producer, monkeypatch, tmp_path
):
    calls = []
    for name in ("download_delivery", "verify_bundle", "verify_index", "verify_cdn"):
        monkeypatch.setattr(audit, name, lambda *args, name=name: calls.append(name) or [])
    result = audit.audit(10, 1, 20, "0.1.1", tmp_path / "bundle")
    assert calls == ["download_delivery", "verify_bundle", "verify_index", "verify_cdn"]
    assert result["audit_kind"] == "read-only-existing-delivery"


def test_failed_pypi_readback_cannot_reach_cdn(producer, monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "download_delivery", lambda *args: None)
    monkeypatch.setattr(audit, "verify_bundle", lambda *args: None)

    def wrong_registry(*args):
        raise ValueError("registry checksum mismatch")

    def forbidden_cdn(*args):
        pytest.fail("unverified registry bytes must never reach the CDN audit")

    monkeypatch.setattr(audit, "verify_index", wrong_registry)
    monkeypatch.setattr(audit, "verify_cdn", forbidden_cdn)
    with pytest.raises(ValueError, match="registry"):
        audit.audit(10, 1, 20, "0.1.1", tmp_path / "bundle")


def test_other_failed_jobs_cannot_be_hidden_by_readback_failure(producer):
    job = copy.deepcopy(producer["jobs"][0])
    job.update(name="unexpected", conclusion="failure")
    producer["jobs"].append(job)
    with pytest.raises(ValueError, match="unrelated"):
        audit.producer(10, 1, 20, "0.1.1")


@pytest.mark.parametrize(
    ("ids", "version", "message"),
    [
        ((0, 1, 20), "0.1.1", "positive integers"),
        ((10, -1, 20), "0.1.1", "positive integers"),
        ((10, 1, True), "0.1.1", "positive integers"),
        ((10, 1, "20"), "0.1.1", "positive integers"),
        ((10, 1, 20), "0.0.0", "final release"),
        ((10, 1, 20), "0.1.1-alpha.1", "final release"),
        ((10, 1, 20), "v0.1.1", "final release"),
        ((10, 1, 20), "01.1.1", "final release"),
    ],
)
def test_invalid_ids_or_non_final_version_rejected_before_api_access(
    producer, ids, version, message
):
    with pytest.raises(ValueError, match=message):
        audit.producer(*ids, version)
    assert producer["source_checks"] == []


def test_annotated_tag_is_dereferenced_to_the_producer_commit(producer, monkeypatch):
    producer["tag"] = {"object": {"type": "tag", "sha": "d" * 40}}
    fixture_api = audit.api

    def api(path):
        if path.endswith("/git/tags/" + "d" * 40):
            return {"object": {"type": "commit", "sha": producer["annotated_target"]}}
        return fixture_api(path)

    monkeypatch.setattr(audit, "api", api)
    producer["annotated_target"] = SHA
    assert audit.producer(10, 1, 20, "0.1.1")["source_sha"] == SHA
    producer["annotated_target"] = "c" * 40
    with pytest.raises(ValueError, match="release tag"):
        audit.producer(10, 1, 20, "0.1.1")


@pytest.mark.parametrize("total_count", [0, 99, "6", None])
def test_incomplete_or_paginated_job_listing_rejected(producer, monkeypatch, total_count):
    fixture_api = audit.api

    def api(path):
        result = fixture_api(path)
        if path.endswith("/attempts/1/jobs?per_page=100"):
            result["total_count"] = total_count
        return result

    monkeypatch.setattr(audit, "api", api)
    with pytest.raises(ValueError, match="one complete verified page"):
        audit.producer(10, 1, 20, "0.1.1")


@pytest.mark.parametrize("missing", ["started_at", "completed_at"])
def test_missing_build_timestamps_rejected(producer, missing):
    build = next(job for job in producer["jobs"] if job["name"] == "build")
    del build[missing]
    with pytest.raises(ValueError, match="complete producer build timestamps"):
        audit.producer(10, 1, 20, "0.1.1")


def test_missing_artifact_timestamp_rejected(producer):
    del producer["artifact"]["created_at"]
    with pytest.raises(ValueError, match="complete producer build timestamps"):
        audit.producer(10, 1, 20, "0.1.1")


def test_archive_symlink_rejected_before_extraction(tmp_path, monkeypatch):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in [
            "cdn/register.js",
            "cdn/webmcp-manifest.schema.json",
            "cdn/inventory.json",
            "dist/ais_webmcp-0.1.1-py3-none-any.whl",
        ]:
            archive.writestr(name, b"fixture")
        link = zipfile.ZipInfo("dist/ais_webmcp-0.1.1.tar.gz")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "/etc/passwd")
    data = output.getvalue()
    monkeypatch.setattr(audit.subprocess, "check_output", lambda cmd: data)
    evidence = {
        "artifact_id": 20,
        "version": "0.1.1",
        "artifact_digest": "sha256:" + hashlib.sha256(data).hexdigest(),
    }
    bundle = tmp_path / "bundle"
    with pytest.raises(ValueError, match="symlinks rejected"):
        audit.download_delivery(evidence, bundle)
    assert not bundle.exists()


def test_cli_writes_the_read_only_audit_report(producer, monkeypatch, tmp_path):
    import json
    import runpy
    import types

    data = archive_bytes()
    producer["artifact"]["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
    stub = types.ModuleType("check_publication")
    stub.api = audit.api
    stub.check_source = lambda *args, **kwargs: None
    stub.verify_bundle = lambda *args: None
    stub.verify_index = lambda *args: None
    stub.verify_cdn = lambda *args: ["register.js"]
    monkeypatch.setitem(sys.modules, "check_publication", stub)
    monkeypatch.setattr("subprocess.check_output", lambda cmd: data)
    report = tmp_path / "out" / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_cdn_release.py",
            "--producer-run-id=10",
            "--producer-attempt=1",
            "--artifact-id=20",
            "--version=0.1.1",
            f"--bundle={tmp_path / 'bundle'}",
            f"--report={report}",
        ],
    )
    runpy.run_path(str(ROOT / "scripts/audit_cdn_release.py"), run_name="__main__")
    result = json.loads(report.read_text())
    assert result["source_sha"] == SHA
    assert result["objects"] == ["register.js"]
    assert result["audit_kind"] == "read-only-existing-delivery"


def test_only_the_removed_release_workflow_is_a_legacy_producer():
    assert audit.LEGACY_PRODUCER_WORKFLOW == ".github/workflows/release.yml"
    assert not (ROOT / audit.LEGACY_PRODUCER_WORKFLOW).exists()
