# Contributor CI and build checks

## Code and metadata checks

`ci.yml` runs the full test matrix for PR opening, new commits, reopening and
base-branch retargeting (`edited` with `changes.base`). Pushes to both `develop`
and `main` also run full CI. Manual CI remains available.

Title/body edits and `ready_for_review` run read-only Repository Policy and a
Quality Gate that **revalidates existing full CI evidence**, without rerunning
its matrix. `run-name` is the trusted `CI full` / `CI metadata` sentinel. Separate
concurrency groups prevent a description edit from cancelling running tests.

The metadata gate checks the latest full PR producer for the same repository,
PR number, head, base SHA/ref and current attempt. It requires its unique genuine
Quality Gate and every configured code contract to have succeeded. A failed or
cancelled newer producer cannot be replaced by an older green run; a previous
metadata carrier cannot be reused recursively. If full CI is still running, it
waits for up to 20 minutes and fails closed on timeout or API/identity errors.
The step summary records the original run, attempt and job IDs and explicitly
states that no tests were rerun. A final PR/producer readback rejects a concurrent
retarget or rerun. Only an isolated Repository Policy failure may coexist with
successful full code evidence, so a title correction needs no second matrix.

A real canary showed that changing the required job name to `PR Metadata Check`
in a newer `ci.yml` suite leaves GitHub expecting its Quality Gate, even with the
older green check present. The static required name therefore remains, backed by
verified full-test evidence rather than a successful result inferred from skips.

Require **both** `WebMCP Quality Gate` and
`repository-policy / Repository Policy` on develop and main. Policy and code
quality are independent: an invalid title can fail Policy while tested code keeps
its green Quality Gate. Correcting the title then runs only metadata checks.

## Local checks and distributions

The contributor setup and local checks are described in the repository
[README](../README.md). The `npm-pack` CI job checks the package allowlist;
the quality gate requires that check alongside the other configured checks.
CI evidence applies to the tested source revision. It does not establish that
a distribution was published or that its published bytes match the source.
For distribution and provenance guidance, see [release-audit.md](release-audit.md).
