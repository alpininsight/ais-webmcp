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
    assert set(local_runs) <= {"ci.yml", "npm-publish.yml"}


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
    # The maintainer process (workflow, environment, approval) lives in
    # docs/release.md. The README is the public PyPI/npm page.
    assert "npm-publish.yml" in release_doc
    assert "npm-ais-webmcp" in release_doc
    assert "alpininsight/ais-webmcp" in release_doc
    assert "release owner's go" in release_doc
    assert "manual bootstrap" in release_doc
    assert "build:release" in release_doc
    assert "Peter" not in release_doc
    assert "Trusted Publishing" in readme
    assert "provenance" in readme
    assert "docs/release.md" in readme
    assert "npm install @alpininsightsolutions/webmcp" in readme
    assert "not yet published" not in readme
    for forbidden in (
        # Internal names: people, environments, private repos, hosts, paths.
        "Peter",
        "npm-ais-webmcp",
        "webmcp_check",
        "insight-ui-webmcp/",
        "insight-ui-webmcp.git",
        "github.com/alpininsight/insight-ui",
        "enterprise",
        "Enterprise",
        "secret/",
        "svc.cluster.local",
    ):
        assert forbidden not in readme, forbidden
    for doc in (readme, release_doc):
        assert "Trusted Publishing" in doc
        assert "provenance" in doc
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
        public_spec_refs = re.sub(r"\bwebmachinelearning/webmcp#[0-9]+\b", "", doc)
        assert re.search(r"[A-Za-z0-9_.-]+#[0-9]+\b", public_spec_refs) is None

    ci = yaml.safe_load((workflows / "ci.yml").read_text())
    guard = ci["jobs"]["npm-pack"]
    assert "scripts/check-npm-pack.cjs" in guard["steps"][-1]["run"]
    assert "npm-pack" in ci["jobs"]["gate"]["needs"]


def test_release_and_cdn_run_in_the_central_executor():
    """Public repositories cannot call private reusables; release/CDN moved out."""
    workflows = ROOT / ".github/workflows"
    for name in ("release.yml", "cdn-develop.yml"):
        assert not (workflows / name).exists(), name
    runbook = (ROOT / "docs/ci-and-release.md").read_text()
    assert "ais-webmcp-release-assets.yml" in runbook
    assert "npm-publish.yml" in runbook
    ci = yaml.safe_load((workflows / "ci.yml").read_text())
    push = ci.get("on", ci.get(True))["push"]["branches"]
    assert set(push) == {"develop", "main"}


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


def test_public_docs_do_not_link_private_repositories():
    """NOTICE and the release runbook stay free of private repository links."""
    notice = (ROOT / "NOTICE").read_text()
    assert "github.com/alpininsight/insight-ui-webmcp" not in notice
    assert "https://insight-ui-webmcp.alpininsight.ai" in notice
    runbook = (ROOT / "docs/ci-and-release.md").read_text()
    assert "alpininsight/.github-private" not in runbook
    assert "ais-webmcp-publish-python.yml" in runbook
