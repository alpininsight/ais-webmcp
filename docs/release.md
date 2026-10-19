# npm release

`@alpininsightsolutions/webmcp` is the public browser runtime. Publishing
runs from `.github/workflows/npm-publish.yml`. It is a manual
`workflow_dispatch` on `main` with a stable `vX.Y.Z` tag. That tag must point
at the `main` commit. The job uses environment `npm-ais-webmcp` and
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
with Peter's go. The first publish is the manual bootstrap from `main`.

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
run there. It stamps the release version before that command. A local
`npm publish` still runs `prepublishOnly`, which rejects the committed
`0.0.0` placeholder.
