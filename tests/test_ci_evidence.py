"""Evidence reuse must preserve code failures and bind the current PR candidate."""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_evidence", ROOT / "scripts/check_ci_evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
REPO = "alpininsight/example"
HEAD = "a" * 40
BASE = "b" * 40
GATE = "WebMCP Quality Gate"
CONTRACTS = ["quality / Quality (3.12)", "quality / Quality Gate"]


@pytest.fixture
def state(monkeypatch):
    pr = {
        "number": 7,
        "state": "open",
        "head": {"sha": HEAD, "ref": "ci/test", "repo": {"full_name": REPO}},
        "base": {"sha": BASE, "ref": "develop", "repo": {"full_name": REPO}},
    }
    run = {
        "id": 10,
        "run_attempt": 2,
        "display_title": "CI full",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "head_sha": HEAD,
        "head_branch": "ci/test",
        "repository": {"full_name": REPO, "id": 42},
        "head_repository": {"full_name": REPO, "id": 42},
        "status": "completed",
        "conclusion": "success",
        "pull_requests": [
            {
                "number": 7,
                "head": {"sha": HEAD, "ref": "ci/test", "repo": {"id": 42}},
                "base": {"sha": BASE, "ref": "develop", "repo": {"id": 42}},
            }
        ],
    }
    names = [GATE, *CONTRACTS, evidence.POLICY]
    jobs = [
        {
            "id": 20 + i,
            "run_id": 10,
            "run_attempt": 2,
            "head_sha": HEAD,
            "name": name,
            "status": "completed",
            "conclusion": "success",
        }
        for i, name in enumerate(names)
    ]
    data = {
        "pr": pr,
        "runs": [run],
        "jobs": {"total_count": len(jobs), "jobs": jobs},
        "calls": [],
        "sleeps": [],
        "pr_reads": 0,
        "run_reads": 0,
    }

    def api(path):
        data["calls"].append(path)
        if path == f"repos/{REPO}/pulls/7":
            data["pr_reads"] += 1
            if data.get("retarget_after_first_read") and data["pr_reads"] > 1:
                changed = copy.deepcopy(data["pr"])
                changed["base"]["sha"] = "c" * 40
                return changed
            return data["pr"]
        if (
            path == f"repos/{REPO}/actions/workflows/ci.yml/runs"
            f"?event=pull_request&head_sha={HEAD}&per_page=100&page=1"
        ):
            data["run_reads"] += 1
            if data.get("rerun_after_first_read") and data["run_reads"] > 1:
                data["runs"][0]["run_attempt"] = 3
            return {"workflow_runs": copy.deepcopy(data["runs"])}
        if path == f"repos/{REPO}/actions/runs/10/jobs?filter=latest&per_page=100":
            return data["jobs"]
        raise AssertionError(path)

    def sleep(seconds):
        data["sleeps"].append(seconds)
        if data.get("finish_on_poll"):
            data["runs"][0]["status"] = "completed"
            data["runs"][0]["conclusion"] = "success"

    monkeypatch.setattr(evidence, "api", api)
    monkeypatch.setattr(evidence.time, "sleep", sleep)
    monkeypatch.setattr(evidence.time, "monotonic", lambda: 0)
    return data


def reuse(**kwargs):
    return evidence.reuse_evidence(REPO, 7, HEAD, BASE, "develop", GATE, CONTRACTS, **kwargs)


def test_reuse_reports_the_original_full_producer_not_new_tests(state):
    receipt = reuse(timeout=0)
    assert receipt["run_id"] == 10 and receipt["run_attempt"] == 2
    assert receipt["quality_gate_job_id"] == 20
    assert receipt["head_sha"] == HEAD and receipt["base_sha"] == BASE
    assert receipt["contracts"][CONTRACTS[0]] == 21
    assert state["pr_reads"] == 2 and state["run_reads"] == 2
    assert not state["sleeps"]
    assert not any("status=success" in p for p in state["calls"])


def test_policy_only_failure_can_be_corrected_without_another_matrix(state):
    state["runs"][0]["conclusion"] = "failure"
    state["jobs"]["jobs"][-1]["conclusion"] = "failure"
    assert reuse(timeout=0)["quality_gate_job_id"] == 20


def test_metadata_runs_are_never_reused_recursively(state):
    metadata = copy.deepcopy(state["runs"][0])
    metadata.update(id=11, display_title="CI metadata")
    state["runs"].insert(0, metadata)
    assert reuse(timeout=0)["run_id"] == 10


def test_missing_full_producer_does_not_treat_metadata_as_full(state):
    state["runs"][0]["display_title"] = "CI metadata"
    with pytest.raises(ValueError, match="Timed out"):
        reuse(timeout=0)


def test_newest_failed_full_cannot_fall_back_to_an_older_green(state):
    older = copy.deepcopy(state["runs"][0])
    older["id"] = 9
    state["runs"].append(older)
    state["runs"][0]["conclusion"] = "failure"
    state["jobs"]["jobs"][0]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="unsuccessful"):
        reuse(timeout=0)
    assert not any("/runs/9/" in p for p in state["calls"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("run_attempt", 0),
        ("head_sha", "c" * 40),
        ("head_branch", "other"),
        ("event", "workflow_dispatch"),
        ("path", ".github/workflows/release.yml"),
        ("display_title", "PR title with CI full"),
        ("repository", {"full_name": "other/repo", "id": 42}),
        ("head_repository", {"full_name": "other/fork"}),
        ("status", "unknown"),
        ("conclusion", "cancelled"),
        ("conclusion", "timed_out"),
    ],
)
def test_rejects_wrong_full_identity_or_cancelled_run(state, field, value):
    state["runs"][0][field] = value
    with pytest.raises(ValueError):
        reuse(timeout=0)


@pytest.mark.parametrize(
    "layer,field,value",
    [
        ("top", "number", 8),
        ("head", "sha", "c" * 40),
        ("head", "ref", "other"),
        ("head", "repo", {"id": 99}),
        ("base", "sha", "c" * 40),
        ("base", "ref", "main"),
        ("base", "repo", {"id": 99}),
    ],
)
def test_rejects_wrong_pr_association_and_base_candidate(state, layer, field, value):
    pr = state["runs"][0]["pull_requests"][0]
    (pr if layer == "top" else pr[layer])[field] = value
    with pytest.raises(ValueError, match="association"):
        reuse(timeout=0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", 9),
        ("run_attempt", 1),
        ("head_sha", "c" * 40),
        ("id", True),
        ("status", "in_progress"),
        ("conclusion", "skipped"),
    ],
)
def test_rejects_stale_or_skipped_gate(state, field, value):
    state["jobs"]["jobs"][0][field] = value
    with pytest.raises(ValueError):
        reuse(timeout=0)


@pytest.mark.parametrize(
    "case", ["missing", "duplicate", "overflow", "hidden", "contract", "extra_failure"]
)
def test_rejects_incomplete_or_failed_job_inventory(state, case):
    data = state["jobs"]
    if case == "missing":
        data["jobs"].pop(0)
        data["total_count"] -= 1
    elif case == "duplicate":
        data["jobs"].append(copy.deepcopy(data["jobs"][0]))
        data["total_count"] += 1
    elif case == "overflow":
        data["total_count"] = 101
    elif case == "hidden":
        data["total_count"] += 1
    elif case == "contract":
        data["jobs"][1]["conclusion"] = "failure"
    else:
        data["jobs"].append(
            {**data["jobs"][0], "id": 99, "name": "extra code check", "conclusion": "failure"}
        )
        data["total_count"] += 1
    with pytest.raises(ValueError):
        reuse(timeout=0)


def test_running_full_producer_is_followed_without_a_new_body_edit(state):
    state["runs"][0].update(status="in_progress", conclusion=None)
    state["finish_on_poll"] = True
    assert reuse(timeout=30)["run_id"] == 10
    assert state["sleeps"] == [15]


def test_bounded_wait_does_not_accept_running_full_gate(state):
    state["runs"][0].update(status="in_progress", conclusion=None)
    with pytest.raises(ValueError, match="Timed out"):
        reuse(timeout=0)


def test_pr_retarget_during_validation_invalidates_evidence(state):
    state["retarget_after_first_read"] = True
    with pytest.raises(ValueError, match="Current PR"):
        reuse(timeout=0)


def test_new_attempt_during_validation_cannot_reuse_the_old_attempt(state):
    state["rerun_after_first_read"] = True
    with pytest.raises(ValueError, match="Timed out"):
        reuse(timeout=0)


def test_bad_api_inventory_fails_closed(state, monkeypatch):
    original = evidence.api

    def malformed(path):
        if "/actions/workflows/" in path:
            return {"workflow_runs": None}
        return original(path)

    monkeypatch.setattr(evidence, "api", malformed)
    with pytest.raises(ValueError, match="Invalid workflow run inventory"):
        reuse(timeout=0)
    assert state["pr_reads"] == 1


def test_invalid_api_json_is_not_accepted(monkeypatch):
    import json

    monkeypatch.setattr(evidence.subprocess, "check_output", lambda *a, **kw: "not JSON")
    with pytest.raises(json.JSONDecodeError):
        evidence.api("repos/alpininsight/example/pulls/7")
