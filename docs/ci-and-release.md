# CI and Python release evidence

## Code and metadata checks

`ci.yml` runs the full test matrix for PR opening, new commits, reopening and
base-branch retargeting (`edited` with `changes.base`). A push to `main` also runs
full CI. Develop pushes do not launch another matrix; the integration and release
promotion PRs provide their own tests. Manual CI remains available.

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

## Source release and one central package producer

The source `release.yml` accepts only the current protected `main` revision,
including when `release=false`. It validates the latest exact-SHA **push** run of
`ci.yml`, its repository, attempt, completed/success result and unique successful
Quality Gate. A PR/dispatch run or an older green attempt cannot substitute for it.
Every validator job explicitly provisions Python 3.14 with pinned `setup-uv` and
runs its standard-library-only validator through `uv run --no-project`. General
runners need no system `python3`, project dependency sync or nested test matrix.
The optional CDN readback jobs own the same runtime prerequisite independently.
GitVersion runs after this validation. Actual release creation additionally needs
the existing activation flag and an exact merged promotion PR into main.

`release=false` performs source/version validation without a nested matrix or
stable wheel/sdist build. `release=true` creates the matching GitHub tag/release and
records a handoff; it does not publish to PyPI. The protected central publisher owns
the stable wheel/sdist build and independent installation tests.

After the source release, run the central build-only producer:

```bash
gh workflow run ais-webmcp-publish-python.yml \
  --repo alpininsight/.github-private --ref main \
  -f source_sha="$SOURCE_SHA" -F publish=false
```

Wait for that producer to finish successfully. Read back its exact run ID, current
attempt and immutable artifact ID from that run and its artifact inventory. Check
that its schema-3 manifest binds this source SHA/version and producer identity.
Set `PRODUCER_RUN_ID`, `PRODUCER_ATTEMPT` and `ARTIFACT_ID` to those verified IDs.
After publication authorization, request reuse of those same tested files:

```bash
gh workflow run ais-webmcp-publish-python.yml \
  --repo alpininsight/.github-private --ref main \
  -f source_sha="$SOURCE_SHA" -F publish=true \
  -f producer_run_id="${PRODUCER_RUN_ID:?}" \
  -f producer_attempt="${PRODUCER_ATTEMPT:?}" \
  -f artifact_id="${ARTIFACT_ID:?}"
```

All three producer IDs are required. No legacy-bundle fallback or second package
build is permitted in the publication run. It must revalidate the producer,
source/CI/release, manifest and file hashes; the existing protected environment,
reviewer, enablement flag and isolated OIDC upload job remain required. A build-only
success is not an upload, CDN receipt, consumer deployment or native-browser proof.

## Separate CDN contract

The existing optional `cdn=true` path retains its delivery build, exact PyPI-file
readback, static-assets publication and independent CDN-byte/header evidence.
The local source build runs only when CDN is explicitly requested. This change
neither enables CDN nor changes its flags, aliases or acceptance requirements.
