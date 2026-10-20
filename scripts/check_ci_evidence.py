"""Read-only reuse of full PR CI; never turn skipped tests into successful tests."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

WORKFLOW = ".github/workflows/ci.yml"
POLICY = "repository-policy / Repository Policy"


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True, timeout=30))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value):
    return type(value) is int and value > 0


def current_pr(repository, number, head, base, base_ref):
    pr = api(f"repos/{repository}/pulls/{number}")
    require(
        pr.get("number") == number
        and pr.get("state") == "open"
        and (pr.get("head") or {}).get("sha") == head
        and (pr.get("base") or {}).get("sha") == base
        and (pr.get("base") or {}).get("ref") == base_ref
        and ((pr.get("head") or {}).get("repo") or {}).get("full_name") == repository
        and ((pr.get("base") or {}).get("repo") or {}).get("full_name") == repository,
        "Current PR head/base/repository changed; full CI for the new candidate is required",
    )
    return pr


def latest_full(repository, head):
    # GitHub returns newest first. Do not filter by success or skip a failed full run.
    for page in range(1, 11):
        data = api(
            f"repos/{repository}/actions/workflows/ci.yml/runs"
            f"?event=pull_request&head_sha={head}&per_page=100&page={page}"
        )
        runs = data.get("workflow_runs")
        require(isinstance(runs, list), "Invalid workflow run inventory")
        for run in runs:
            mode = run.get("display_title")
            if mode == "CI metadata":
                continue
            require(mode == "CI full", "Unknown CI mode; only a full producer may supply evidence")
            return run
        if len(runs) < 100:
            return None
    raise ValueError("Full CI exceeds the verified run inventory window")


def validate_run(run, repository, number, head, base, base_ref, head_ref):
    require(
        positive(run.get("id"))
        and positive(run.get("run_attempt"))
        and run.get("path") == WORKFLOW
        and run.get("event") == "pull_request"
        and run.get("head_sha") == head
        and run.get("head_branch") == head_ref
        and (run.get("repository") or {}).get("full_name") == repository
        and (run.get("head_repository") or {}).get("full_name") == repository,
        "Full CI workflow/repository/head/attempt identity mismatch",
    )
    pulls = run.get("pull_requests")
    repo_id = (run.get("repository") or {}).get("id")
    require(
        isinstance(pulls, list) and len(pulls) == 1 and positive(repo_id),
        "Ambiguous CI PR association",
    )
    pr = pulls[0]
    require(
        pr.get("number") == number
        and (pr.get("head") or {}).get("sha") == head
        and (pr.get("head") or {}).get("ref") == head_ref
        and ((pr.get("head") or {}).get("repo") or {}).get("id") == repo_id
        and (pr.get("base") or {}).get("sha") == base
        and (pr.get("base") or {}).get("ref") == base_ref
        and ((pr.get("base") or {}).get("repo") or {}).get("id") == repo_id,
        "Full CI PR/head/base/fork association mismatch",
    )


def validate_jobs(run, head, gate_name, contracts):
    data = api(
        f"repos/{run['repository']['full_name']}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100"
    )
    jobs = data.get("jobs")
    total = data.get("total_count")
    require(
        type(total) is int and 0 < total <= 100 and isinstance(jobs, list) and len(jobs) == total,
        "Invalid or incomplete CI job inventory",
    )
    for job in jobs:
        require(
            positive(job.get("id"))
            and job.get("run_id") == run["id"]
            and job.get("run_attempt") == run["run_attempt"]
            and job.get("head_sha") == head
            and job.get("status") == "completed",
            "CI job identity/attempt/status mismatch",
        )
    required = {}
    for name in [gate_name, *contracts]:
        matches = [j for j in jobs if j.get("name") == name]
        require(
            len(matches) == 1 and matches[0].get("conclusion") == "success",
            f"Missing, ambiguous or unsuccessful full CI contract: {name}",
        )
        required[name] = matches[0]["id"]
    failed = [
        j.get("name") for j in jobs if j.get("conclusion") not in {"success", "skipped", "neutral"}
    ]
    require(not failed or failed == [POLICY], "Full CI contains a failed/cancelled code contract")
    require(
        (run.get("conclusion") == "success" and not failed)
        or (run.get("conclusion") == "failure" and failed == [POLICY]),
        "Full CI may fail only for independent Repository Policy with successful code contracts",
    )
    return required


def reuse_evidence(
    repository,
    number,
    head,
    base,
    base_ref,
    gate_name,
    contracts,
    *,
    timeout=1200,
    poll_interval=15,
):
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None,
        "Invalid repository",
    )
    require(positive(number), "Invalid PR number")
    require(
        all(re.fullmatch(r"[0-9a-f]{40}", s) for s in [head, base]),
        "Full head/base SHAs are required",
    )
    require(base_ref in {"develop", "main"}, "Invalid PR base ref")
    require(
        gate_name in {"WebMCP Quality Gate", "Enterprise Quality Gate"}
        and isinstance(contracts, list)
        and bool(contracts)
        and all(isinstance(n, str) and n for n in contracts)
        and len(set(contracts)) == len(contracts)
        and gate_name not in contracts,
        "Invalid full CI contract inventory",
    )
    require(timeout >= 0 and poll_interval > 0, "Invalid evidence wait budget")
    deadline = time.monotonic() + timeout
    while True:
        pr = current_pr(repository, number, head, base, base_ref)
        head_ref = pr["head"]["ref"]
        run = latest_full(repository, head)
        if run is not None:
            validate_run(run, repository, number, head, base, base_ref, head_ref)
            if run.get("status") == "completed":
                require(
                    run.get("conclusion") in {"success", "failure"},
                    "Latest full CI was cancelled or did not finish normally",
                )
                contracts_proof = validate_jobs(run, head, gate_name, contracts)
                # Re-read the PR and producer: no stale pass after a retarget or rerun.
                current_pr(repository, number, head, base, base_ref)
                fresh = latest_full(repository, head)
                if (
                    fresh is not None
                    and fresh.get("id") == run["id"]
                    and fresh.get("run_attempt") == run["run_attempt"]
                    and fresh.get("status") == "completed"
                    and fresh.get("conclusion") == run["conclusion"]
                ):
                    validate_run(fresh, repository, number, head, base, base_ref, head_ref)
                    return {
                        "schema": 1,
                        "repository": repository,
                        "pull_request": number,
                        "head_sha": head,
                        "base_sha": base,
                        "base_ref": base_ref,
                        "workflow": WORKFLOW,
                        "run_id": run["id"],
                        "run_attempt": run["run_attempt"],
                        "quality_gate_job_id": contracts_proof[gate_name],
                        "contracts": contracts_proof,
                    }
            else:
                require(
                    run.get("status")
                    in {"queued", "in_progress", "waiting", "pending", "requested"},
                    "Invalid full CI status",
                )
        remaining = deadline - time.monotonic()
        require(remaining > 0, "Timed out waiting for the latest full CI evidence")
        time.sleep(min(poll_interval, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--contracts", required=True, type=json.loads)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    receipt = reuse_evidence(
        args.repository, args.pr, args.head, args.base, args.base_ref, args.gate, args.contracts
    )
    text = json.dumps(receipt, indent=2)
    print(text)
    if args.summary:
        with args.summary.open("a") as f:
            f.write(
                "## Reused full CI evidence\n\n"
                "No tests were rerun by this metadata event. "
                "The existing full producer and its code contracts were revalidated.\n\n```json\n"
                + text
                + "\n```\n"
            )


if __name__ == "__main__":
    main()
