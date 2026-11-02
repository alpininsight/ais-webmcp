# Read-only release delivery audit

A successful upload and a successful public readback are separate checks. The
publication verifier identifies itself as
`AlpinInsight-WebMCP-PublicationVerifier/1.0`, sends `Accept: */*`, and reads each
canonical URL in full. It does not imitate a browser, use challenge cookies, or
relax status, redirect, content, CORS, or cache checks.

The former `cdn-develop.yml` workflow with `mode=release-audit` was removed together
with `release.yml` (see `docs/ci-and-release.md`). `scripts/audit_cdn_release.py`
remains only for historical producer runs of the removed `release.yml` (it rejects
every other workflow path, and fails closed once their artifacts have expired) and can be run locally with
`--producer-run-id`, `--producer-attempt`, `--artifact-id` and `--version` (without a
leading `v`). It needs only repository read permissions; it does not build packages,
upload PyPI or CDN objects, read R2 credentials, or change edge configuration.

The auditor requires the exact completed main release workflow and attempt,
current protected main source and matching release tag, successful source,
build, PyPI verification, and CDN upload jobs. Only the original public
readback may have failed. It verifies the original artifact archive digest,
creation within that build attempt, source inventory and package hashes against
PyPI, then all nine immutable/main/latest CDN objects against the original
delivery. An expired artifact or moved main/tag fails closed.

A successful audit retains an independent JSON receipt. It does not rewrite the
original failed run. Repair future verification on `develop`; do not rebuild or
overwrite an already published immutable version to repair a readback client.

New releases are produced by the central executor, which runs the same
`check_publication.py` readbacks (`verify_index`, `verify_cdn`) itself. A separate
audit mode for executor runs is not part of this repository (Empfehlung).
