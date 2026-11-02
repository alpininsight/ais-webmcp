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

## Release and CDN run in the central executor

This repository is public. GitHub does not let public repositories call private
reusable workflows, so the former `release.yml` and `cdn-develop.yml` were removed.
GitHub releases and CDN uploads now run in the organisation's central publishing
repository (set `PUBLISHER_REPO` to it) through `ais-webmcp-release-assets.yml`.
That executor checks out this repository at an exact source SHA. It accepts only
the current protected `develop` or `main` head whose latest exact-SHA **push** run
of `ci.yml` completed successfully; `ci.yml` therefore runs on pushes to both
branches. `publish=false` builds only; publication needs the executor's own
activation flag.

```bash
gh workflow run ais-webmcp-release-assets.yml \
  --repo "${PUBLISHER_REPO:?}" --ref main \
  -f source_channel=main -f source_sha="$SOURCE_SHA" -f target=release -F publish=true
```

npm publication stays in this repository (`npm-publish.yml`), because npm
Trusted Publishing is bound to this repository and workflow file.

After the source release, run the build-only producer workflow in the
organisation's central publishing repository (set `PUBLISHER_REPO` to it):

```bash
gh workflow run ais-webmcp-publish-python.yml \
  --repo "${PUBLISHER_REPO:?}" --ref main \
  -f source_sha="$SOURCE_SHA" -F publish=false
```

Wait for that producer to finish successfully. Read back its exact run ID, current
attempt and immutable artifact ID from that run and its artifact inventory. Check
that its schema-3 manifest binds this source SHA/version and producer identity.
Set `PRODUCER_RUN_ID`, `PRODUCER_ATTEMPT` and `ARTIFACT_ID` to those verified IDs.
After publication authorization, request reuse of those same tested files:

```bash
gh workflow run ais-webmcp-publish-python.yml \
  --repo "${PUBLISHER_REPO:?}" --ref main \
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

After PyPI publication, run the executor with `target=cdn` for `main`. It keeps the
delivery build, exact PyPI-file readback (`check_publication.py bundle/index`),
static-assets publication and independent CDN-byte/header evidence
(`check_publication.py cdn`). `source_channel=develop` publishes only the mutable
`develop` preview alias.
