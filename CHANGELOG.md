# Changelog

## Unreleased

- Publish npm releases from the GitHub-hosted runner `ubuntu-24.04`, in one
  concurrency group. `prepublishOnly` rejects the `0.0.0` placeholder.
  Trusted-publisher setup must allow direct `npm publish`.
- Type the browser runtime as one CommonJS export. Tool specs accept named
  interfaces, manifests include `$schema`, `anchors`, and `notes`, and
  manifest-level errors are not typed as results with required `ok`.
- Pin Node 24 for repository development with `.nvmrc` and `devEngines`.
  The published package does not set `engines`.
- Inject `package.json`'s version into `InsightUiWebmcp.version` when
  building `register.js`. Publish syncs that version from the Python package
  before the build.
- Prepare the public npm package `@alpininsightsolutions/webmcp` for the
  browser runtime. The tarball allowlist is the built bundle, its types,
  README, LICENSE, and NOTICE. Enterprise paths, `webmcp_check`, and `.env`
  files fail the pack guard. Publish uses Trusted Publishing from an `npm-v*`
  tag on main and does not store an npm token.
- Accept an optional Draft 2020-12 `outputSchema` (alias `output_schema`) on
  each tool. A present schema is validated; a missing one stays valid and is
  reported as finding code `missing_output_schema` at severity `low`.
  `register.js` copies a valid output schema onto the registered tool.
  `output_schema` and validation `findings` are appended after the existing
  constructor fields. A circular output schema is an invalid schema, not an
  uncaught rejection.
- Split the framework-independent core, CLI, schema and browser runtime from
  insight-ui-webmcp at `d6ead80843dbe42096791dd6688ed58a35dc3291`.
- Preserve filtered core history; use an independent package/version/build.
- Carry the complete third-party runtime-license fix from upstream PR #60.
- Move CDN ownership and full public readback to the `ais-webmcp` namespace.
- Ship the shared negative corpus for installed-core contract checks.

Shared pre-split history:
https://github.com/alpininsight/insight-ui-webmcp/tree/d6ead80843dbe42096791dd6688ed58a35dc3291
