"""Require the latest full push CI on the exact current Main commit."""

import json
import re
import subprocess
import sys

REPOSITORY = "alpininsight/ais-webmcp"
JOBS = {
    "quality / Quality (3.12)",
    "quality / Quality (3.13)",
    "quality / Quality (3.14)",
    "quality / Quality Gate",
    "quality / Gitleaks",
    "Minimum supported dependencies",
    "assets / Static Assets",
    "npm tarball guard",
    "WebMCP Quality Gate",
}


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True, timeout=30))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main(sha):
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "invalid source SHA")
    root = f"repos/{REPOSITORY}"
    require(api(f"{root}/commits/main")["sha"] == sha, "Main moved")
    runs = api(
        f"{root}/actions/workflows/ci.yml/runs?event=push&branch=main&head_sha={sha}&per_page=100"
    )
    candidates = runs.get("workflow_runs")
    require(isinstance(candidates, list) and candidates, "missing Main CI")
    run = candidates[0]
    require(
        run.get("path") == ".github/workflows/ci.yml"
        and run.get("event") == "push"
        and run.get("head_sha") == sha
        and run.get("head_branch") == "main"
        and (run.get("repository") or {}).get("full_name") == REPOSITORY
        and (run.get("head_repository") or {}).get("full_name") == REPOSITORY
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and type(run.get("id")) is int
        and run["id"] > 0
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] > 0,
        "latest Main CI is not successful for this exact source",
    )
    data = api(f"{root}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    jobs = data.get("jobs")
    require(
        isinstance(jobs, list) and data.get("total_count") == len(jobs) <= 100, "incomplete jobs"
    )
    for name in JOBS:
        matches = [job for job in jobs if job.get("name") == name]
        require(
            len(matches) == 1
            and matches[0].get("head_sha") == sha
            and matches[0].get("run_id") == run["id"]
            and matches[0].get("status") == "completed"
            and matches[0].get("conclusion") == "success",
            f"missing successful Main CI job: {name}",
        )
    require(api(f"{root}/commits/main")["sha"] == sha, "Main moved during verification")
    fresh = api(f"{root}/actions/runs/{run['id']}")
    require(
        fresh.get("run_attempt") == run["run_attempt"] and fresh.get("conclusion") == "success",
        "CI rerun changed",
    )
    latest = api(
        f"{root}/actions/workflows/ci.yml/runs?event=push&branch=main&head_sha={sha}&per_page=100"
    )
    require(
        latest.get("workflow_runs") and latest["workflow_runs"][0].get("id") == run["id"],
        "newer Main CI appeared",
    )
    return {"source_sha": sha, "run_id": run["id"], "run_attempt": run["run_attempt"]}


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv[1])))
    except (ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Main CI verification failed: {error}") from error
