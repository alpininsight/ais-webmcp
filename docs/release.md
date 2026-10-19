# npm release

`@alpininsightsolutions/webmcp` is the public browser runtime. Publishing
runs in this repository. `.github/workflows/npm-publish.yml` is the canonical
npm standard from `alpininsight/.github-private`. A public repository cannot
call a private reusable workflow, and npm Trusted Publishing requires the
publish to run here on a GitHub-hosted runner, so the job uses
`ubuntu-latest`. It is a manual `workflow_dispatch` on `main` with a
`vX.Y.Z` tag input, environment `npm-ais-webmcp`, and permissions
`contents: read` and `id-token: write`. It checks out that tag, installs
Node from `.nvmrc` with npm >= 11.5.1, runs `npm ci` and `npm run check:pack`,
stamps the tag with `scripts/sync-npm-version.cjs`, injects that version with
`npm run build:js`, then runs
`npm publish --provenance --access public --ignore-scripts`.
No npm token. The trusted publisher is bound to GitHub repository
`alpininsight/ais-webmcp`, workflow filename `npm-publish.yml`, and
environment `npm-ais-webmcp`. A release goes out only with Peter's go. The
first publish is the manual bootstrap from `main`.

## Version

The committed `package.json` version is the `0.0.0` placeholder. It is not a
second version source. `js/register.source.cjs` keeps that same placeholder.
`scripts/build-js.cjs` replaces it in the built bundle with `package.json`'s
version, so `InsightUiWebmcp.version` matches the npm package.

The workflow takes the `vX.Y.Z` tag, strips the leading `v`, and
`scripts/sync-npm-version.cjs` writes that exact `MAJOR.MINOR.PATCH` into
`package.json`. That tag is the same release version
`scripts/build_delivery.py` stamps into the Python package. The next step
runs `npm run build:js`, which injects it into `register.js`. `0.0.0` and
pre-release versions are refused.

## One-time setup on npmjs.com

Owner: Peter. Publish only with Peter's go.

1. Sign in at [npmjs.com](https://www.npmjs.com) as an owner of the
   `alpininsightsolutions` organization. Create that organization if it does
   not exist. The package scope is `@alpininsightsolutions`.
2. Add a GitHub Actions trusted publisher for `@alpininsightsolutions/webmcp`
   (organization trusted publishers for a package that does not exist yet, or
   the package's Settings → Trusted Publisher after it exists):
   - GitHub organization or user: `alpininsight`
   - Repository: `ais-webmcp`
   - Workflow filename: `npm-publish.yml`
   - Environment name: `npm-ais-webmcp`
   - Allowed actions: enable direct `npm publish`. `npm stage publish` is
     always allowed. Trusted publishers created after 3 September 2026 default
     to staged publishing only. This workflow publishes directly and attaches
     provenance, so leave the publisher able to publish directly.
3. In this repository's Actions settings, create an environment named
   `npm-ais-webmcp`. Add the usual required reviewers. Add no secrets and no
   npm token. The publish job sets that environment.
4. Do not create an npm automation token or granular access token. The first
   publish is the manual bootstrap: run `npm-publish.yml` with
   `workflow_dispatch` from `main`, and only with Peter's go.

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

The workflow publishes with `--ignore-scripts`, so `prepublishOnly` does not
run there. It stamps the release version before that command. A local
`npm publish` still runs `prepublishOnly`, which rejects the committed
`0.0.0` placeholder.
