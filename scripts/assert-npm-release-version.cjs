"use strict";

/**
 * Refuse npm publish of the committed 0.0.0 placeholder.
 *
 * prepublishOnly runs this before npm packs the tarball. The publish workflow
 * stamps GitVersion into package.json first, so a real release still passes.
 */

const { assertReleaseVersion } = require("./sync-npm-version.cjs");
const pkg = require("../package.json");

function assertProvenance(env) {
  const provenance = env.npm_config_provenance === "true";
  const file = Boolean(env.npm_config_provenance_file?.trim());
  if (provenance === file) {
    throw new Error("npm publish requires exactly one of --provenance or --provenance-file");
  }
}

if (require.main === module) {
  try {
    assertReleaseVersion(pkg.version);
    assertProvenance(process.env);
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  }
}

module.exports = { assertProvenance };
