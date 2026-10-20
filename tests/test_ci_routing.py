"""Execute the workflow routing and gates without GitHub or publication credentials."""

import os
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
    assert events["push"]["branches"] == ["main"]
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
        ("metadata", "success", "failure", "skipped skipped", 1),
        ("metadata", "success", "skipped", "skipped skipped", 1),
        ("metadata", "success", "success", "success skipped", 1),
        ("metadata", "failure", "success", "skipped skipped", 1),
        ("unknown", "success", "success", "success success", 1),
        ("full", "success", "success", "", 1),
        ("full", "success", "success", "success", 1),
    ],
)
def test_execute_quality_and_metadata_gates(mode, classify, policy, contracts, expected):
    step = WORKFLOW["jobs"]["gate"]["steps"][0]
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
            "CONTRACT_RESULTS": contracts,
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode != 0) == bool(expected), result.stderr


def test_metadata_never_emits_the_required_quality_gate():
    jobs = WORKFLOW["jobs"]
    gate = jobs["gate"]
    quality_name = "Enterprise Quality Gate" if "redis-contract" in jobs else "WebMCP Quality Gate"
    assert gate["name"] == (
        "${{ needs.classify.outputs.mode == 'metadata' && 'PR Metadata Check' || '"
        + quality_name
        + "' }}"
    )
    contracts = set(gate["needs"]) - {"repository-policy", "classify"}
    assert contracts
    for name in contracts:
        assert jobs[name]["needs"] == "classify"
        assert jobs[name]["if"] == "needs.classify.outputs.mode == 'full'"
        assert "${{ needs." + name + ".result }}" in gate["steps"][0]["env"]["CONTRACT_RESULTS"]
    assert gate["steps"][0]["env"]["POLICY_RESULT"] == "${{ needs.repository-policy.result }}"
