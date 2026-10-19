# npm release

`@alpininsightsolutions/webmcp` is the public browser runtime. This repository
does not publish it. Releases are published by the central publisher in
`alpininsight/.github-private`, workflow
`.github/workflows/ais-webmcp-publish-npm.yml`, GitHub environment
`npm-ais-webmcp`. That publisher uses npm Trusted Publishing (OIDC) and
attaches provenance. It does not use an npm token. A release goes out only
with Peter's go. The publisher workflow is added in
`alpininsight/.github-private`, not in this repository.

## Version

The committed `package.json` version is the `0.0.0` placeholder. It is not a
second version source. `js/register.source.cjs` keeps that same placeholder.
`scripts/build-js.cjs` replaces it in the built bundle with `package.json`'s
version, so `InsightUiWebmcp.version` matches the npm package.

The publisher reads GitVersion `major_minor_patch` — the same value
`scripts/build_delivery.py` stamps into the Python package — and
`scripts/sync-npm-version.cjs` writes that exact `MAJOR.MINOR.PATCH` into
`package.json`. The next step runs `npm run build:js`, which injects it into
`register.js`. `0.0.0` and pre-release versions are refused.

## One-time setup on npmjs.com

Owner: Peter. Publish only with Peter's go.

1. Sign in at [npmjs.com](https://www.npmjs.com) as an owner of the
   `alpininsightsolutions` organization. Create that organization if it does
   not exist. The package scope is `@alpininsightsolutions`.
2. Add a GitHub Actions trusted publisher for `@alpininsightsolutions/webmcp`
   (organization trusted publishers for a package that does not exist yet, or
   the package's Settings → Trusted Publisher after it exists):
   - GitHub organization or user: `alpininsight`
   - Repository: `.github-private`
   - Workflow filename: `ais-webmcp-publish-npm.yml`
   - Environment name: `npm-ais-webmcp`
   - Allowed actions: enable direct `npm publish`. `npm stage publish` is
     always allowed. Trusted publishers created after 3 September 2026 default
     to staged publishing only. The central publisher publishes directly and
     attaches provenance, so leave the publisher able to publish directly.
3. The environment `npm-ais-webmcp` is created on
   `alpininsight/.github-private`, not in this repository. Add no secrets and
   no npm token.
4. Do not create an npm automation token or granular access token. This
   repository has no publish workflow.

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
placeholder. The central publisher stamps the release version before that
command.
