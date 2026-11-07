"""Reject unrelated, stale or incomplete Actions evidence before creating a release."""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "source_publication", ROOT / "scripts/check_publication.py"
)
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)
REPO = "alpininsight/ais-webmcp"
SHA = "a" * 40


@pytest.fixture
def evidence(monkeypatch):
    state = {
        "branch": {"protected": True, "commit": {"sha": SHA}},
        "runs": {
            "workflow_runs": [
                {
                    "id": 10,
                    "run_attempt": 2,
                    "head_sha": SHA,
                    "head_branch": "main",
                    "event": "push",
                    "path": ".github/workflows/ci.yml",
                    "repository": {"full_name": REPO},
                    "head_repository": {"full_name": REPO},
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        },
        "jobs": {
            "total_count": 1,
            "jobs": [
                {
                    "id": 20,
                    "run_id": 10,
                    "run_attempt": 2,
                    "head_sha": SHA,
                    "name": "WebMCP Quality Gate",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        },
        "summaries": [{"number": 7}],
        "pull": {
            "number": 7,
            "merged": True,
            "state": "closed",
            "draft": False,
            "merged_at": "2026-10-20T08:00:00Z",
            "merge_commit_sha": SHA,
            "base": {"ref": "main", "repo": {"full_name": REPO}},
        },
        "calls": [],
    }

    def api(path):
        state["calls"].append(path)
        if path == f"repos/{REPO}/branches/main":
            return state["branch"]
        if (
            path
            == f"repos/{REPO}/actions/workflows/ci.yml/runs?branch=main&event=push&head_sha={SHA}&per_page=1"
        ):
            return state["runs"]
        if path == f"repos/{REPO}/actions/runs/10/jobs?filter=latest&per_page=100":
            return state["jobs"]
        if path == f"repos/{REPO}/commits/{SHA}/pulls?per_page=100&page=1":
            return state["summaries"]
        if path == f"repos/{REPO}/pulls/7":
            return state["pull"]
        raise AssertionError(f"unexpected API call: {path}")

    monkeypatch.setattr(publication, "api", api)
    return state


def test_probe_reuses_latest_main_ci_without_review_or_rebuild(evidence):
    assert publication.check_source(REPO, SHA) == {
        "source_ci_run": 10,
        "source_ci_attempt": 2,
        "source_quality_job": 20,
    }
    assert not any("/pulls" in p or "/reviews" in p or "check-runs" in p for p in evidence["calls"])
    assert not any("status=success" in p for p in evidence["calls"])


@pytest.mark.parametrize("protected,head", [(False, SHA), (True, "b" * 40)])
def test_probe_rejects_unprotected_or_changed_main(evidence, protected, head):
    evidence["branch"] = {"protected": protected, "commit": {"sha": head}}
    with pytest.raises(ValueError, match="protected main"):
        publication.check_source(REPO, SHA)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("run_attempt", 0),
        ("head_sha", "b" * 40),
        ("head_branch", "develop"),
        ("event", "pull_request"),
        ("path", ".github/workflows/release.yml"),
        ("repository", {"full_name": "other/fork"}),
        ("head_repository", {"full_name": "other/fork"}),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("conclusion", "cancelled"),
    ],
)
def test_probe_rejects_wrong_latest_run_even_when_older_run_passed(evidence, field, value):
    evidence["runs"]["workflow_runs"][0][field] = value
    with pytest.raises(ValueError, match="latest exact-SHA"):
        publication.check_source(REPO, SHA)


def test_probe_rejects_missing_main_ci(evidence):
    evidence["runs"]["workflow_runs"] = []
    with pytest.raises(ValueError, match="main push"):
        publication.check_source(REPO, SHA)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("run_id", 9),
        ("run_attempt", 1),
        ("head_sha", "b" * 40),
        ("status", "queued"),
        ("conclusion", "failure"),
        ("conclusion", "skipped"),
    ],
)
def test_probe_rejects_stale_or_non_successful_gate(evidence, field, value):
    evidence["jobs"]["jobs"][0][field] = value
    with pytest.raises(ValueError, match="Quality Gate"):
        publication.check_source(REPO, SHA)


@pytest.mark.parametrize("mode", ["missing", "duplicate", "overflow"])
def test_probe_rejects_ambiguous_gate_inventory(evidence, mode):
    if mode == "missing":
        evidence["jobs"]["jobs"] = []
    elif mode == "duplicate":
        evidence["jobs"]["jobs"].append(copy.deepcopy(evidence["jobs"]["jobs"][0]))
    else:
        evidence["jobs"]["total_count"] = 101
    with pytest.raises(ValueError):
        publication.check_source(REPO, SHA)


def test_release_also_requires_merged_exact_main_promotion(evidence):
    publication.check_source(REPO, SHA, require_merged_pr=True)
    assert any("/pulls/7" in p for p in evidence["calls"])
    assert not any("/reviews" in p for p in evidence["calls"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("merged", False),
        ("draft", True),
        ("state", "open"),
        ("merged_at", None),
        ("merge_commit_sha", "b" * 40),
        ("base", {"ref": "develop", "repo": {"full_name": REPO}}),
        ("base", {"ref": "main", "repo": {"full_name": "other/fork"}}),
    ],
)
def test_release_rejects_unrelated_or_unmerged_pr(evidence, field, value):
    evidence["pull"][field] = value
    with pytest.raises(ValueError, match="merged PR into main"):
        publication.check_source(REPO, SHA, require_merged_pr=True)


@pytest.mark.parametrize("repo,sha", [("other/fork", SHA), (REPO, "main"), (REPO, "A" * 40)])
def test_source_identity_rejects_wrong_repository_or_revision(evidence, repo, sha):
    with pytest.raises(ValueError):
        publication.check_source(repo, sha)
    assert evidence["calls"] == []
