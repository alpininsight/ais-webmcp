# npm release

`@alpininsightsolutions/webmcp` is the public browser runtime. The publish
workflow is `.github/workflows/npm-publish.yml`. It uses the GitHub
environment `npm-release` and Trusted Publishing (OIDC). It does not use an
npm token, `NODE_AUTH_TOKEN`, or any repository secret.

## Version

The committed `package.json` version is the `0.0.0` placeholder. It is not a
second version source. `js/register.source.cjs` keeps that same placeholder.
`scripts/build-js.cjs` replaces it in the built bundle with `package.json`'s
version, so `InsightUiWebmcp.version` matches the npm package.

On publish, the workflow reads GitVersion `major_minor_patch` — the same value
`scripts/build_delivery.py` stamps into the Python package — and
`scripts/sync-npm-version.cjs` writes that exact `MAJOR.MINOR.PATCH` into
`package.json`. The next step runs `npm run build:js`, which injects it into
`register.js`. `0.0.0` and pre-release versions are refused. A tag publish
must be named `npm-vX.Y.Z` for that same version.
`npm-v*` is separate from the Python `v*` release tag so GitVersion does not
treat the npm tag as its own version tag.

## One-time setup on npmjs.com

Owner: Peter.

1. Sign in at [npmjs.com](https://www.npmjs.com) as an owner of the
   `alpininsightsolutions` organization. Create that organization if it does
   not exist. The package scope is `@alpininsightsolutions`.
2. Add a GitHub Actions trusted publisher for `@alpininsightsolutions/webmcp`
   (organization trusted publishers for a package that does not exist yet, or
   the package's Settings → Trusted Publisher after it exists):
   - GitHub organization or user: `alpininsight`
   - Repository: `ais-webmcp`
   - Workflow filename: `npm-publish.yml`
   - Environment name: `npm-release`
   - Allowed actions: enable direct `npm publish`. `npm stage publish` is
     always allowed. Trusted publishers created after 3 September 2026 default
     to staged publishing only. This workflow runs `npm publish` directly, so
     leave the publisher able to publish directly.
3. In the GitHub repository settings, create an Actions environment named
   `npm-release`. Limit it to `main` (and `npm-v*` tags, if the environment
   rules distinguish tags). Add the usual required reviewers. Add no secrets.
4. Do not create an npm automation token or granular access token for this
   workflow. The first publish is a `npm-vX.Y.Z` tag on `main`, or
   `workflow_dispatch` from `main`. Both wait on the `npm-release` environment,
   then run the build check, tests, and tarball guard before
   `npm publish --provenance --access public`.

## Enterprise code never goes to npm

Only the built browser bundle, its types, `README.md`, `LICENSE`, and
`NOTICE` are in the `files` allowlist. npm also packs `package.json`. The
tarball guard (`scripts/check-npm-pack.cjs`, CI job `npm-pack`) runs
`npm pack --dry-run --json` and fails when any other path is present, when
`LICENSE` or `NOTICE` is missing, or when any path matches `enterprise/`,
`webmcp_check`, or `.env`.

Python sources, tests, schemas, delivery scripts, and anything under an
enterprise tree stay in the repository. They are not part of the npm package.

The published `package.json` does not set `engines`. Node 24 is the
repository pin (`.nvmrc` and `devEngines`). `devEngines` applies when
someone works in this source tree; installing the browser runtime does not
warn on other Node versions.

`npm publish` runs `prepublishOnly`, which rejects the committed `0.0.0`
placeholder. The workflow stamps the release version before that command.
Every publish shares the concurrency group `webmcp-npm-publish`, so tag and
manual releases cannot publish at the same time. The publish job runs on the
GitHub-hosted runner `ubuntu-24.04`. npm Trusted Publishing does not accept
self-hosted runners, including this repo's `general` label.
