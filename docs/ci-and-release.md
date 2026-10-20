# CI and Python release evidence

## Code and metadata checks

`ci.yml` runs the full test matrix for PR opening, new commits, reopening and
base-branch retargeting (`edited` with `changes.base`). A push to `main` also runs
full CI. Develop pushes do not launch another matrix; the integration and release
promotion PRs provide their own tests. Manual CI remains available.

Title/body edits and `ready_for_review` run only the read-only central Repository
Policy and `PR Metadata Check`. Their concurrency group is separate from full CI,
so editing a description cannot cancel running tests. Only full CI produces
`WebMCP Quality Gate`; skipped tests must never produce that successful check.

Require **both** `WebMCP Quality Gate` and
`repository-policy / Repository Policy` on develop and main. Policy and code
quality are independent: an invalid title can fail Policy while tested code keeps
its green Quality Gate. Correcting the title then runs only metadata checks.

## Source release and one central package producer

The source `release.yml` accepts only the current protected `main` revision,
including when `release=false`. It validates the latest exact-SHA **push** run of
`ci.yml`, its repository, attempt, completed/success result and unique successful
Quality Gate. A PR/dispatch run or an older green attempt cannot substitute for it.
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
