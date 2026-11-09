"""Execute the workflow routing and gates without GitHub or publication credentials."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
METADATA = (
    "github.event_name == 'pull_request' && !github.event.changes.base && "
    "(github.event.action == 'edited' || github.event.action == 'ready_for_review')"
)


def test_events_and_concurrency_preserve_main_and_isolate_metadata():
    events = WORKFLOW.get("on", WORKFLOW.get(True))
    assert events["push"]["branches"] == ["develop", "main"]
    assert set(events["pull_request"]["types"]) == {
        "opened",
        "synchronize",
        "reopened",
        "edited",
        "ready_for_review",
    }
    group = WORKFLOW["concurrency"]["group"]
    assert "github.event.pull_request.number || github.ref" in group
    assert "${{ " + METADATA + " && 'metadata' || 'full' }}" in group
    classify = WORKFLOW["jobs"]["classify"]
    assert classify["steps"][0]["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "ACTION": "${{ github.event.action }}",
        "BASE_CHANGED": "${{ github.event.changes.base != null }}",
    }
    assert not any("uses" in step for step in classify["steps"])
    policy = WORKFLOW["jobs"]["repository-policy"]
    assert policy["if"] == "github.event_name == 'pull_request'"
    assert policy["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_candidate_dispatch_uses_separate_concurrency_group():
    group = WORKFLOW["concurrency"]["group"]
    legacy = (
        "webmcp-ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}-"
        "${{ " + METADATA + " && 'metadata' || 'full' }}"
    )
    suffix = (
        "${{ github.event_name == 'workflow_dispatch' && "
        "inputs.candidate_tag != '' && '-candidate' || '' }}"
    )
    # The unchanged prefix preserves all existing groups; the sole new
    # expression adds a suffix only for a candidate dispatch.
    assert group == legacy + suffix
    assert WORKFLOW["concurrency"]["cancel-in-progress"] is True
    for event, tag, expected_suffix in [
        ("push", "", ""),
        ("pull_request", "", ""),
        ("workflow_call", "", ""),
        ("workflow_dispatch", "", ""),
        ("workflow_dispatch", "v1.2.3", "-candidate"),
        ("push", "v1.2.3", ""),
    ]:
        actual_suffix = "-candidate" if event == "workflow_dispatch" and tag != "" else ""
        assert actual_suffix == expected_suffix
        assert legacy + actual_suffix == (legacy + suffix).replace(suffix, expected_suffix)
    assert legacy != legacy + "-candidate"


@pytest.mark.parametrize(
    "event,action,base_changed,expected",
    [
        ("pull_request", "opened", "false", "full"),
        ("pull_request", "synchronize", "false", "full"),
        ("pull_request", "reopened", "false", "full"),
        ("pull_request", "edited", "true", "full"),
        ("pull_request", "edited", "false", "metadata"),
        ("pull_request", "ready_for_review", "false", "metadata"),
        ("pull_request", "ready_for_review", "true", "full"),
        ("push", "", "false", "full"),
        ("workflow_dispatch", "", "false", "full"),
        ("workflow_call", "", "false", "full"),
    ],
)
def test_execute_routing_for_code_metadata_and_base_retarget(
    tmp_path, event, action, base_changed, expected
):
    output = tmp_path / "output"
    step = WORKFLOW["jobs"]["classify"]["steps"][0]
    subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            "EVENT_NAME": event,
            "ACTION": action,
            "BASE_CHANGED": base_changed,
            "GITHUB_OUTPUT": str(output),
        },
        check=True,
    )
    assert output.read_text() == f"mode={expected}\n"


@pytest.mark.parametrize(
    "mode,classify,policy,contracts,expected",
    [
        ("full", "success", "success", "success success", 0),
        # A later title-only correction must not need a second matrix.
        ("full", "success", "failure", "success success", 0),
        ("full", "success", "skipped", "success success", 0),
        ("full", "success", "success", "failure success", 1),
        ("full", "success", "success", "cancelled success", 1),
        ("full", "success", "success", "skipped success", 1),
        ("metadata", "success", "success", "skipped skipped", 0),
        ("metadata", "success", "failure", "skipped skipped", 0),
        ("metadata", "success", "skipped", "skipped skipped", 0),
        ("metadata", "success", "success", "success skipped", 1),
        ("metadata", "failure", "success", "skipped skipped", 1),
        ("unknown", "success", "success", "success success", 1),
        ("full", "success", "success", "", 1),
        ("full", "success", "success", "success", 1),
    ],
)
def test_execute_quality_and_metadata_gates(mode, classify, policy, contracts, expected):
    step = WORKFLOW["jobs"]["gate"]["steps"][-1]
    expected_count = int(step["env"]["EXPECTED_CONTRACTS"])
    if len(contracts.split()) == 2:
        contracts += " " + " ".join([contracts.split()[-1]] * (expected_count - 2))
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            "EXPECTED_CONTRACTS": str(expected_count),
            "MODE": mode,
            "CLASSIFY_RESULT": classify,
            "POLICY_RESULT": policy,
            "EVIDENCE_RESULT": "success",
            "CONTRACT_RESULTS": contracts,
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode != 0) == bool(expected), result.stderr


def test_metadata_quality_gate_requires_explicit_full_evidence():
    jobs = WORKFLOW["jobs"]
    gate = jobs["gate"]
    quality_name = "Enterprise Quality Gate" if "redis-contract" in jobs else "WebMCP Quality Gate"
    assert gate["name"] == quality_name
    contracts = set(gate["needs"]) - {"repository-policy", "classify"}
    assert contracts
    for name in contracts:
        assert jobs[name]["needs"] == "classify"
        assert jobs[name]["if"] == "needs.classify.outputs.mode == 'full'"
        assert "${{ needs." + name + ".result }}" in gate["steps"][-1]["env"]["CONTRACT_RESULTS"]
    assert gate["steps"][-1]["env"]["EVIDENCE_RESULT"] == "${{ steps.evidence.outcome }}"
    assert gate["permissions"] == {"contents": "read", "actions": "read", "pull-requests": "read"}
    evidence = next(step for step in gate["steps"] if step.get("id") == "evidence")
    assert evidence["if"] == "needs.classify.outputs.mode == 'metadata'"
    assert "base/scripts/check_ci_evidence.py" in evidence["run"]
    checkout = next(step for step in gate["steps"] if "actions/checkout@" in step.get("uses", ""))
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert checkout["with"]["path"] == "base"
    assert checkout["with"]["persist-credentials"] is False
    assert "--summary" in evidence["run"]
    assert not evidence.get("continue-on-error")
    assert WORKFLOW["run-name"] == "${{ " + METADATA + " && 'CI metadata' || 'CI full' }}"


@pytest.mark.parametrize("outcome", ["skipped", "failure", "cancelled", ""])
def test_metadata_gate_cannot_pass_without_verified_evidence(outcome):
    step = WORKFLOW["jobs"]["gate"]["steps"][-1]
    count = step["env"]["EXPECTED_CONTRACTS"]
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            "MODE": "metadata",
            "CLASSIFY_RESULT": "success",
            "EVIDENCE_RESULT": outcome,
            "EXPECTED_CONTRACTS": count,
            "CONTRACT_RESULTS": " ".join(["skipped"] * int(count)),
        },
        capture_output=True,
    )
    assert result.returncode != 0


def test_gitleaks_binary_is_hash_pinned_and_pre_commit_has_no_token():
    install = next(
        step
        for step in WORKFLOW["jobs"]["gitleaks"]["steps"]
        if step.get("name") == "Install Gitleaks"
    )
    assert len(install["env"]["GITLEAKS_SHA256"]) == 64
    assert "sha256sum --check --strict" in install["run"]
    assert (
        install["env"]["GITLEAKS_SHA256"]
        == "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
    )
    for step in WORKFLOW["jobs"]["quality"]["steps"]:
        if step.get("name") == "Run pre-commit":
            assert "GH_TOKEN" not in str(step.get("env", {}))
    root = Path(__file__).resolve().parents[1]
    if shutil.which("git") is None or not (root / ".git").exists():
        pytest.skip("needs a git checkout (not available in an sdist)")
    # CI strips the gitleaks hook from the working copy before pre-commit runs,
    # so compare against the committed config.
    pre_commit = yaml.safe_load(
        subprocess.run(
            ["git", "show", "HEAD:.pre-commit-config.yaml"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    hook_rev = next(
        repo["rev"] for repo in pre_commit["repos"] if repo["repo"].endswith("/gitleaks")
    )
    assert install["env"]["GITLEAKS_VERSION"] == hook_rev.removeprefix("v")
