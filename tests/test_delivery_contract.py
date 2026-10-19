"""Fail-closed publication/provenance and workflow policy checks."""

import hashlib
import importlib.util
import io
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication", ROOT / "scripts/check_publication.py")
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def test_ci_uses_central_repository_policy():
    """Branch routing lives in repository-policy-reusable, not a local script."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    policy = workflow["jobs"]["repository-policy"]
    assert policy["if"] == "github.event_name == 'pull_request'"
    assert policy["uses"].endswith("/.github/workflows/repository-policy-reusable.yml@main")
    assert "branch-policy" not in workflow["jobs"]
    assert "repository-policy" in workflow["jobs"]["gate"]["needs"]
    callers = {
        path.name: yaml.safe_load(path.read_text())
        for path in (ROOT / ".github/workflows").glob("*.yml")
    }
    assert callers["scheduled-pre-commit-update.yml"]["jobs"]["autoupdate"]["uses"].endswith(
        "/scheduled-pre-commit-update-reusable.yml@main"
    )
    local_runs = [
        name
        for name, body in callers.items()
        if any("runs-on" in job for job in body["jobs"].values())
    ]
    assert set(local_runs) <= {"ci.yml", "release.yml", "npm-publish.yml"}


@pytest.mark.parametrize(
    "protected,head,check",
    [
        (False, "a" * 40, "success"),
        (True, "b" * 40, "success"),
        (True, "a" * 40, "failure"),
    ],
)
def test_publication_requires_protected_source_and_check(monkeypatch, protected, head, check):
    def api(path):
        if path.endswith("branches/main"):
            return {"protected": protected, "commit": {"sha": head}}
        return {"check_runs": [{"id": 1, "name": "WebMCP Quality Gate", "conclusion": check}]}

    monkeypatch.setattr(publication, "api", api)
    with pytest.raises(ValueError):
        publication.check_source("alpininsight/insight-ui-webmcp", "a" * 40)


def test_publication_needs_no_pr_review(monkeypatch):
    """Owner decision 2026-10-12: approval lives in the pypi-<project> environment."""
    calls = []

    def api(path):
        calls.append(path)
        if path.endswith("branches/main"):
            return {"protected": True, "commit": {"sha": "a" * 40}}
        if "check-runs" in path:
            return {
                "check_runs": [{"id": 1, "name": "WebMCP Quality Gate", "conclusion": "success"}]
            }
        raise AssertionError(f"unexpected API call {path}")

    monkeypatch.setattr(publication, "api", api)
    publication.check_source("alpininsight/insight-ui-webmcp", "a" * 40)
    assert not any("/reviews" in c or "/pulls" in c for c in calls)


def test_npm_publish_runs_in_this_repository():
    """The publish workflow is the npm publication template. No private caller."""
    workflows = ROOT / ".github/workflows"
    workflow_path = workflows / "npm-publish.yml"
    text = workflow_path.read_text()
    workflow_text = "\n".join(path.read_text() for path in sorted(workflows.glob("*.yml")))
    assert "npm-release" not in workflow_text
    assert re.search(r"npm-v(?!ersion)", workflow_text) is None
    assert "npm-publish-reusable.yml" not in workflow_text
    assert (
        hashlib.sha256(workflow_path.read_bytes()).hexdigest()
        == "d9f3e48e9fe78d326dd4bcc2985b75c6b8425455cdb97749052a82dae3b106e5"
    )
    workflow = yaml.safe_load(text)
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["tag"]["required"] is True
    permissions = {"contents": "read", "id-token": "write"}
    assert workflow["permissions"] == permissions
    assert "secrets" not in workflow
    publish = workflow["jobs"]["publish"]
    assert publish["if"] == "github.ref == 'refs/heads/main'"
    assert publish["runs-on"] == "ubuntu-latest"
    assert publish["environment"] == "npm-${{ github.event.repository.name }}"
    assert "permissions" not in publish
    assert "secrets" not in publish
    assert "uses" not in publish
    joined = "\n".join(step.get("run", "") for step in publish["steps"])
    assert "npm ci --ignore-scripts" in joined
    assert "npm run check:pack" in joined
    assert "scripts/sync-npm-version.cjs" not in joined
    assert "npm run build:release --if-present" in joined
    assert "npm pack --ignore-scripts" in joined
    assert "npm publish --provenance --access public --ignore-scripts" in joined
    checkout = next(
        step
        for step in publish["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["uses"].startswith("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
    assert checkout["with"]["ref"] == "${{ inputs.tag }}"
    assert checkout["with"]["persist-credentials"] is False
    node = next(
        step
        for step in publish["steps"]
        if str(step.get("uses", "")).startswith("actions/setup-node@")
    )
    assert node["uses"].startswith("actions/setup-node@820762786026740c76f36085b0efc47a31fe5020")
    assert node["with"]["node-version"] == "${{ steps.node.outputs.version }}"
    assert "registry-url" not in node["with"]

    package = json.loads((ROOT / "package.json").read_text())
    assert package["name"] == "@alpininsightsolutions/webmcp"
    assert package["license"] == "Apache-2.0"
    assert {"LICENSE", "NOTICE"} <= set(package["files"])
    assert package["scripts"]["build:release"] == "npm run build:js"
    assert package["repository"]["url"] == "git+https://github.com/alpininsight/ais-webmcp.git"
    nvmrc = (ROOT / ".nvmrc").read_text().strip().removeprefix("v")
    parts = [int(part) for part in nvmrc.split(".")]
    parts += [0] * (3 - len(parts))
    assert tuple(parts) >= (22, 14, 0)
    assert (ROOT / "scripts/check-npm-pack.cjs").is_file()
    assert (ROOT / "scripts/sync-npm-version.cjs").is_file()
    assert (ROOT / "src/ais_webmcp/assets/register.d.ts").is_file()

    readme = (ROOT / "README.md").read_text()
    release_doc = (ROOT / "docs/release.md").read_text()
    for doc in (readme, release_doc):
        assert "npm-publish.yml" in doc
        assert "npm-ais-webmcp" in doc
        assert "alpininsight/ais-webmcp" in doc
        assert "Peter's go" in doc
        assert "Trusted Publishing" in doc
        assert "provenance" in doc
        assert "manual bootstrap" in doc
        assert "build:release" in doc
        for forbidden in (
            "npm-publish-reusable.yml",
            ".github-private",
            "ubuntu-latest",
            "CDN",
            "cdn.",
            "Cloudflare",
            "OpenBao",
            "self-hosted",
            "npm-release",
            "ais-webmcp-publish-npm.yml",
        ):
            assert forbidden not in doc, forbidden
        assert re.search(r"npm-v(?!ersion)", doc) is None
        assert re.search(r"\bR2\b", doc) is None
        assert re.search(r"\bk8s\b", doc) is None

    ci = yaml.safe_load((workflows / "ci.yml").read_text())
    guard = ci["jobs"]["npm-pack"]
    assert "scripts/check-npm-pack.cjs" in guard["steps"][-1]["run"]
    assert "npm-pack" in ci["jobs"]["gate"]["needs"]


def test_cdn_workflow_cannot_promote_preview_to_latest():
    preview = yaml.safe_load((ROOT / ".github/workflows/cdn-develop.yml").read_text())
    config = preview["jobs"]["cdn"]["with"]
    assert config["update_latest"] is False
    assert config["cdn_upload_immutable"] is False
    assert config["cdn_aliases"] == "develop"
    assert config["cdn_mutable_cache_max_age"] == "300"
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert release["jobs"]["cdn"]["needs"] == ["pypi-verified", "version"]
    assert release["jobs"]["cdn"]["with"]["cdn_asset_globs"] == "*.js,*.json"


def test_release_has_no_pypi_upload_and_hands_off_per_package():
    """PyPI Trusted Publishing lives in .github-private, one entry point per project."""
    text = (ROOT / ".github/workflows/release.yml").read_text()
    release = yaml.safe_load(text)
    assert "pypa/gh-action-pypi-publish" not in text
    assert all("environment" not in job for job in release["jobs"].values())
    assert all("id-token" not in (job.get("permissions") or {}) for job in release["jobs"].values())
    triggers = release.get("on", release.get(True))
    assert set(triggers["workflow_dispatch"]["inputs"]) == {"release", "cdn"}
    assert release["jobs"]["release"]["if"] == "inputs.release"
    handoff = str(release["jobs"]["handoff"])
    for workflow in ("ais-webmcp-publish-python.yml",):
        assert workflow in handoff
    assert "insight-ui-webmcp-publish-python.yml" not in handoff
    assert "publish=false" in handoff
    assert "publish=true" not in handoff


def test_cdn_requires_own_pypi_project_first():
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    gate = release["jobs"]["pypi-verified"]
    assert gate["if"] == "inputs.cdn"
    assert "build" in gate["needs"]
    run = gate["steps"][-1]["run"]
    assert "check_publication.py bundle" in run
    assert "check_publication.py index --version" in run
    assert "--project" not in run
    source = str(release["jobs"]["source"])
    assert "WEBMCP_PYPI_PUBLISH_ENABLED" in source
    assert "refs/heads/main" in source
    assert "CDN_REQUESTED" in source and "CDN_ENABLED" in source
    assert "WEBMCP_CDN_PUBLISH_ENABLED" in source
    evidence = release["jobs"]["cdn-verified"]
    assert set(evidence["needs"]) == {"cdn", "build", "version"}
    assert "check_publication.py cdn" in str(evidence)


def _nested_permissions(workflow):
    requested = {}
    for job in workflow["jobs"].values():
        for scope, level in (job.get("permissions") or workflow.get("permissions") or {}).items():
            if level != "none":
                requested[scope] = "write" if "write" in {level, requested.get(scope)} else level
    return requested


def test_ci_callers_grant_nested_permissions():
    """A reusable caller granting less than ci.yml's jobs request fails at startup."""
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    requested = _nested_permissions(ci)
    assert requested.get("pull-requests") == "read"
    for name in ("release.yml", "cdn-develop.yml"):
        workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
        caller = workflow["jobs"]["quality"]
        assert caller["uses"] == "./.github/workflows/ci.yml"
        granted = caller.get("permissions") or workflow.get("permissions") or {}
        for scope, level in requested.items():
            assert granted.get(scope) in ({"write"} if level == "write" else {"read", "write"}), (
                name,
                scope,
            )


@pytest.mark.parametrize(
    "remote",
    [
        {},
        {"ais_webmcp-1.2.3-py3-none-any.whl": "0" * 64},
        "extra",
    ],
)
def test_registry_readback_is_exact(monkeypatch, tmp_path, remote):
    dist = tmp_path / "dist"
    dist.mkdir()
    digests = {}
    for name in (
        "ais_webmcp-1.2.3-py3-none-any.whl",
        "ais_webmcp-1.2.3.tar.gz",
    ):
        (dist / name).write_bytes(name.encode())
        digests[name] = hashlib.sha256(name.encode()).hexdigest()

    def urlopen(url, timeout):
        project = "ais_webmcp" if "/ais-webmcp/" in url else "insight_ui_webmcp"
        files = {k: v for k, v in digests.items() if k.startswith(project + "-")}
        if remote == "extra":
            files[f"{project}-1.2.3-py2-none-any.whl"] = "1" * 64
        elif project == "ais_webmcp":
            files = remote
        payload = {"urls": [{"filename": k, "digests": {"sha256": v}} for k, v in files.items()]}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(publication.urllib.request, "urlopen", urlopen)
    with pytest.raises(ValueError):
        publication.verify_index(tmp_path, "1.2.3")


def test_registry_readback_accepts_exact_match(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    for name in (
        "ais_webmcp-1.2.3-py3-none-any.whl",
        "ais_webmcp-1.2.3.tar.gz",
    ):
        (dist / name).write_bytes(name.encode())

    def urlopen(url, timeout):
        project = "ais_webmcp" if "/ais-webmcp/" in url else "insight_ui_webmcp"
        payload = {
            "urls": [
                {
                    "filename": p.name,
                    "digests": {"sha256": hashlib.sha256(p.read_bytes()).hexdigest()},
                }
                for p in dist.glob(project + "-*")
            ]
        }
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(publication.urllib.request, "urlopen", urlopen)
    publication.verify_index(tmp_path, "1.2.3")
