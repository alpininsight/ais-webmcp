# npm release

`@alpininsightsolutions/webmcp` is the public browser runtime. Publishing
runs from `.github/workflows/npm-publish.yml`. It is a manual
`workflow_dispatch` on `main` with a stable `vX.Y.Z` tag. That tag must identify
an accepted release commit reachable from `main`. Later Main fixes do not
change an older tag or its distribution contents. The job uses environment
`npm-ais-webmcp` and
permissions `contents: read` and `id-token: write`. It checks out the tag,
installs Node from `.nvmrc` (Node 24) and npm 11.5.1, runs
`npm ci --ignore-scripts` and `npm run check:pack`, then stamps the tag into
`package.json`. The stamp keeps the `@alpininsightsolutions` scope, license
`Apache-2.0`, a files allowlist that includes `LICENSE` and `NOTICE`, and
repository URL `git+https://github.com/alpininsight/ais-webmcp.git`. It then
runs `npm run build:release`, packs the tarball, and runs
`npm publish --provenance --access public --ignore-scripts` on that file.
Trusted Publishing attaches provenance. No npm token. The trusted publisher
is bound to GitHub repository `alpininsight/ais-webmcp`, workflow filename
`npm-publish.yml`, and environment `npm-ais-webmcp`. A release goes out only
with the release owner's go. The initial owner bootstrap is separate from
this OIDC workflow.

## Version

The committed `package.json` version is the `0.0.0` placeholder. It is not a
second version source. `js/register.source.cjs` keeps that same placeholder.
`scripts/build-js.cjs` replaces it in the built bundle with `package.json`'s
version, so `InsightUiWebmcp.version` matches the npm package.

The workflow takes the `vX.Y.Z` tag, strips the leading `v`, and writes
that exact `MAJOR.MINOR.PATCH` into `package.json`. That tag is the same
release version as the Python package. The stamp refuses `0.0.0`,
pre-release versions, a private package, and a files allowlist that omits
`LICENSE` or `NOTICE`. The next step runs `npm run build:release`, which
builds `register.js` from that version.

## First publication and trusted-publisher setup

A package must exist on npm before its package-level Trusted Publisher can be
configured. Do not dispatch this OIDC workflow for a name that has not yet
completed its maintainer-owned first-publication setup. An npm organization
and an authenticated owner alone are not a Trusted Publisher or publication
receipt. See the current [npm Trusted Publishing documentation](https://docs.npmjs.com/trusted-publishers/)
and [`npm trust`](https://docs.npmjs.com/cli/v11/commands/npm-trust/).

After source review and promotion, the release owner can approve a separate
hosted preparation run of `ci.yml` on Main with an accepted candidate tag. The accepted
nonzero stable tag must point to exactly the current Main commit, whose full
push CI must have passed. The job builds the final package, signs its exact
tarball with Sigstore, verifies its identity and uploads a short-lived artifact
with the tarball, bundle and source/CI receipt. This is preparation only: it
does not publish, stage, configure trust or use an npm publishing credential.
No preparation run has yet established an actual Sigstore or registry result.
Candidate dispatches use a separate concurrency group, so they do not cancel
Main push CI. Preparation requires a successful push CI for the exact Main
commit; the candidate's own manual CI is not a substitute for that evidence.

For the manual bootstrap, the owner independently checks the artifact against the approved tag, commit,
run and attempt. With npm 12.2.2 installed, verify the saved bundle using
`node scripts/release-candidate.cjs verify TAG package.tgz provenance.sigstore.json SOURCE_SHA RUN_ID ATTEMPT`.
The owner later handles authentication and required 2FA and separately decides
whether to publish that exact tarball with `--provenance-file`; neither a
successful preparation nor this document is publication approval. Never repack
after signing. The committed `0.0.0` source placeholder cannot be published.

Once the package exists, its GitHub Actions Trusted Publisher must match:

- GitHub organization: `alpininsight`
- Repository: `ais-webmcp`
- Workflow filename: `npm-publish.yml`
- Environment: `npm-ais-webmcp`
- Direct-publish permission: required by this workflow's `npm publish`
  command; a stage-only connection is insufficient.

The matching GitHub environment requires the normal release approval and
accepts Main only. Do not add an npm token to this workflow. A newly configured
publisher must be validated within npm's documented expiry period; verify the
actual current connection before publishing.

For every release, validate the exact tag's dependencies and actual packed
files. An audit of current Main is not evidence for an older tag. After the
approved workflow completes, independently read back the registry version,
tarball integrity and provenance, then install that registry tarball in a
fresh JavaScript/TypeScript consumer. A successful local pack or build is not
publication evidence.

## Enterprise code never goes to npm

Only the built browser bundle, its types, `README.md`, `LICENSE`, and
`NOTICE` are in the `files` allowlist. npm also packs `package.json`. The
tarball guard (`scripts/check-npm-pack.cjs`) runs `npm pack --dry-run --json`
and fails when any other path is present, when
`LICENSE` or `NOTICE` is missing, or when any path matches `enterprise/`,
`webmcp_check`, or `.env`.

Python sources, tests, schemas, delivery scripts, and anything under an
enterprise tree stay in the repository. They are not part of the npm package.

The published `package.json` does not set `engines`. Node 24 is the
repository pin (`.nvmrc` and `devEngines`). `devEngines` applies when
someone works in this source tree; installing the browser runtime does not
warn on other Node versions.

The workflow publishes with `--ignore-scripts`, so `prepublishOnly` does not
run there. It stamps the release version before that command. A local source
`npm publish` runs `prepublishOnly`, which rejects the committed `0.0.0`
placeholder and requires exactly one provenance option. npm does not run that
source lifecycle guard when publishing a prebuilt tarball; the owner must use
the separately verified bundle for the first publication.
