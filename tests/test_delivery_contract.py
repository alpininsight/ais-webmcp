"""Fail-closed publication/provenance and workflow policy checks."""

import hashlib
import importlib.util
import io
import json
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
    "protected,head,check,approved",
    [
        (False, "a" * 40, "success", True),
        (True, "b" * 40, "success", True),
        (True, "a" * 40, "failure", True),
        (True, "a" * 40, "success", False),
    ],
)
def test_publication_requires_source_check_and_review(
    monkeypatch, protected, head, check, approved
):
    def api(path):
        if path.endswith("branches/main"):
            return {"protected": protected, "commit": {"sha": head}}
        if "check-runs" in path:
            return {"check_runs": [{"id": 1, "name": "WebMCP Quality Gate", "conclusion": check}]}
        if "/reviews" in path:
            return [
                {
                    "user": {"login": "reviewer"},
                    "state": "APPROVED" if approved else "CHANGES_REQUESTED",
                    "commit_id": "c" * 40,
                }
            ]
        return [
            {
                "merged_at": "now",
                "base": {"ref": "main"},
                "head": {"sha": "c" * 40},
                "user": {"login": "author"},
                "number": 1,
            }
        ]

    monkeypatch.setattr(publication, "api", api)
    with pytest.raises(ValueError):
        publication.check_source("alpininsight/insight-ui-webmcp", "a" * 40)


def test_npm_publish_is_trusted_publishing_without_tokens():
    """npm Trusted Publishing is OIDC on npm-release. No token, no secret."""
    text = (ROOT / ".github/workflows/npm-publish.yml").read_text()
    assert "secrets." not in text
    assert text.count("NODE_AUTH_TOKEN") == 1
    assert text.count("NPM_TOKEN") == 1
    assert 'test -z "${NODE_AUTH_TOKEN:-}"' in text
    assert 'test -z "${NPM_TOKEN:-}"' in text
    workflow = yaml.safe_load(text)
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["npm-v*"]}
    assert workflow["permissions"] == {"contents": "read"}
    version = workflow["jobs"]["version"]
    assert version["uses"].endswith("/gitversion-reusable.yml@main")
    assert version["with"]["checkout_ref"] == "${{ github.sha }}"
    publish = workflow["jobs"]["publish"]
    assert publish["environment"] == "npm-release"
    assert publish["permissions"] == {"contents": "read", "id-token": "write"}
    assert publish["runs-on"] == "general"
    assert "secrets" not in publish
    joined = "\n".join(step.get("run", "") for step in publish["steps"])
    assert "npm run check:js-build" in joined
    assert "npm test" in joined
    assert "scripts/check-npm-pack.cjs" in joined
    assert "scripts/sync-npm-version.cjs" in joined
    assert "npm run build:js" in joined
    assert "npm publish --provenance --access public" in joined
    runs = [step.get("run", "") for step in publish["steps"]]
    stamp = next(index for index, run in enumerate(runs) if "sync-npm-version.cjs" in run)
    assert runs[stamp + 1].strip() == "npm run build:js"
    assert "npm@11.5.1" in joined
    assert "refs/heads/main" in joined
    assert "refs/tags/npm-v" in joined
    node = next(
        step
        for step in publish["steps"]
        if str(step.get("uses", "")).startswith("actions/setup-node@")
    )
    assert node["uses"].startswith("actions/setup-node@820762786026740c76f36085b0efc47a31fe5020")
    assert node["with"]["node-version"] == "24"
    assert "registry-url" not in node["with"]
    checkout = next(
        step
        for step in publish["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["uses"].startswith("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
    assert checkout["with"]["persist-credentials"] is False
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
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
