# Changelog

## Unreleased

- Pass `outputSchema` through to `document.modelContext.registerTool()`
  unchanged. Chrome 159 and later accept it. If the browser rejects the
  member as unsupported, registration is retried once without it. Optional
  `validateOutput: true` warns when a result misses the schema and still
  returns the result. The check is off by default and is not full JSON Schema
  validation. Mismatch behavior remains open in webmachinelearning/webmcp#92.
- A schema that is not a JSON object, or not a valid Draft 2020-12 schema,
  is an error. A missing `outputSchema` stays a low finding.
- Publish PyPI project URLs for this repository, its issue tracker, and
  `CHANGELOG.md` on the `develop` branch. The Apache-2.0 license stays a
  PEP 639 `License-Expression`, and the OSI Apache license classifier is set.
  The package is not marked `Typing :: Typed`.
- `ais-webmcp validate` rejects invisible or control characters in tool
  names, ids, titles, and descriptions, and rejects empty or whitespace-only
  descriptions. Tool descriptions over 750 code points, schema descriptions
  over 500, and parameter names over 128 are a low finding
  `oversized_schema_field` and do not fail the manifest.
- A missing `outputSchema` stays a low `missing_output_schema` finding.
  A tool that omits `readOnlyHint` adds a low `hints_not_safety_assurances`
  finding: missing `readOnlyHint`, `destructiveHint`, and `openWorldHint`
  must not be treated as safe. Side effects stay on `consequentialHint`.
  Hint defaults on `registerTool` are unchanged. `getTools` and `executeTool`
  are unchanged.

## 0.1.2 (2026-11-02)

- Prepare the browser runtime for npm as `@alpininsightsolutions/webmcp`
  (Trusted Publishing and provenance); the first npm release is pending. The
  README describes the npm package and no longer names internal repositories, hosts, environments or
  people; the maintainer process lives in `docs/release.md`.
- Point the npm `homepage` at https://insight-ui-webmcp.alpininsight.ai/.
  The `bugs` URL stays explicit (the GitHub issue tracker) so npm does not
  derive it on its own; the repository is public before the first npm
  publish, which provenance requires anyway.

- Cover the remaining release-audit guards with tests: invalid producer IDs,
  non-final versions, annotated tags, paginated job listings, missing build
  timestamps, archive symlinks and the report-writing CLI. The README no longer
  names a repository URL in the npm section.

## 0.1.0 and 0.1.1

- Separate PR metadata policy checks from code CI, remove duplicate Develop-push
  matrices, and reuse exact Main-push evidence for source releases. Build stable
  Python files once in the central producer and publish the reviewed bundle by
  immutable producer/run/attempt/artifact IDs. Keep CDN evidence separate.

- Document `npm install @alpininsightsolutions/webmcp`, the
  `InsightUiWebmcp` import, and `window.InsightUiWebmcp` from a script tag.
  The packages-at-a-glance diagram shows the same `register.js` runtime from
  PyPI, npm, and the CDN.
- Publish npm releases from `.github/workflows/npm-publish.yml` in this
  repository on `ubuntu-latest`. The file is the organisation's canonical npm
  publish workflow. It checks out the `vX.Y.Z` tag, stamps that
  version, and runs `npm publish --provenance --access public
  --ignore-scripts`. The trusted publisher is `alpininsight/ais-webmcp`,
  workflow `npm-publish.yml`, environment `npm-ais-webmcp`. Releases go out
  only with the release owner's go. The first publish is the manual bootstrap.
  `prepublishOnly` rejects the `0.0.0` placeholder for a local publish.
- Type the browser runtime as one CommonJS export. Tool specs accept named
  interfaces, either `id` or `name`, and exactly one input-schema alias whose
  `type` is `"object"`. At most one of `outputSchema` or `output_schema` is
  set. Handler maps keep their known keys, manifests include `$schema`,
  `anchors`, and `notes`, and manifest-level errors are not typed as results
  with required `ok`.
- Pin Node 24 for repository development with `.nvmrc` and `devEngines`.
  The published package does not set `engines`.
- Inject `package.json`'s version into `InsightUiWebmcp.version` when
  building `register.js`. Publish syncs that version from the Python package
  before the build.
- Prepare the public npm package `@alpininsightsolutions/webmcp` for the
  browser runtime. The tarball allowlist is the built bundle, its types,
  README, LICENSE, and NOTICE. Enterprise paths, `webmcp_check`, and `.env`
  files fail the pack guard. CI job `npm-pack` runs that guard.
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
- Carry the complete third-party runtime-license fix from insight-ui-webmcp.
- Move CDN ownership and full public readback to the `ais-webmcp` namespace.
- Ship the shared negative corpus for installed-core contract checks.
