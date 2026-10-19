# Changelog

## Unreleased

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
