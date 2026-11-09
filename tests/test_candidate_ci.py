"""Main CI evidence is tied to the exact producer and attempt."""

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("candidate_ci", ROOT / "scripts/check-main-ci.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)
SHA = "a" * 40


def test_candidate_job_is_manual_main_only_and_has_no_publisher_credential():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["prepare"]
    assert "github.event_name == 'workflow_dispatch'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert "github.ref_protected" in job["if"]
    assert "inputs.candidate_tag != ''" in job["if"]
    assert job["environment"] == "npm-ais-webmcp"
    assert job["permissions"] == {"contents": "read", "actions": "read", "id-token": "write"}
    assert workflow["permissions"] == {"contents": "read"}
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "npm publish" not in commands
    assert "npm stage" not in commands
    assert "npm trust" not in commands
    assert "secrets." not in str(job)
    checkout = job["steps"][0]["with"]
    assert checkout["ref"] == "${{ github.sha }}"
    assert checkout["persist-credentials"] is False


def test_exact_main_ci_and_failures(monkeypatch):
    run = {
        "id": 17,
        "run_attempt": 2,
        "path": ".github/workflows/ci.yml",
        "event": "push",
        "head_sha": SHA,
        "head_branch": "main",
        "repository": {"full_name": ci.REPOSITORY},
        "head_repository": {"full_name": ci.REPOSITORY},
        "status": "completed",
        "conclusion": "success",
    }
    jobs = [
        {
            "name": name,
            "head_sha": SHA,
            "run_id": 17,
            "status": "completed",
            "conclusion": "success",
        }
        for name in ci.JOBS
    ]

    def api(path):
        if "/commits/main" in path:
            return {"sha": SHA}
        if "/attempts/" in path:
            return {"total_count": len(jobs), "jobs": jobs}
        if "/workflows/" in path:
            return {"workflow_runs": [run]}
        return run

    monkeypatch.setattr(ci, "api", api)
    assert ci.main(SHA) == {"source_sha": SHA, "run_id": 17, "run_attempt": 2}
    jobs[0]["conclusion"] = "skipped"
    with pytest.raises(ValueError, match="missing successful Main CI job"):
        ci.main(SHA)
    jobs[0]["conclusion"] = "success"
    run["head_sha"] = "b" * 40
    with pytest.raises(ValueError, match="latest Main CI"):
        ci.main(SHA)
