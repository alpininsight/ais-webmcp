# Contributing

Contributions of code are welcome. By contributing, you agree that your
contribution is licensed under the Apache License 2.0, the license of this
repository. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Development setup

Use Python 3.12, 3.13, or 3.14, and Node 24 (`.nvmrc`). From a clone of this
repository, start on the latest `develop`:

```bash
git fetch origin develop
git checkout -b feat/short-description origin/develop
uv sync --locked --all-groups
npm ci
```

Node 24 applies to work in this source tree (`.nvmrc` and `devEngines`). It
is not an install requirement of the published browser package.

## Tests

```bash
uv run --locked pytest
npm test
npm run check:js-build
node scripts/check-npm-pack.cjs
uv run --locked pre-commit run --all-files
```

`npm test` runs the JavaScript tests and the TypeScript check.
`node scripts/check-npm-pack.cjs` is the npm tarball guard, the same check
as the CI job `npm-pack`.

## Pull requests

Open pull requests against `develop`. Keep each pull request to one
objective, and include the checks you ran.

A pull request into `develop` must come from a branch whose name starts
with one of these prefixes and a slash: `build`, `chore`, `ci`,
`dependabot`, `docs`, `feat`, `feature`, `fix`, `perf`, `refactor`,
`renovate`, `revert`, `style`, `test`.

The pull request title, and each commit headline, must be a Conventional
Commit. The type is `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
`refactor`, `revert`, `style`, or `test`, optionally followed by a scope in
parentheses, then a colon and a subject. For example: `feat: add API cache`.

Do not commit directly to `develop` or `main`. Do not commit secrets. Keep
public repository content public.
