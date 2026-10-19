"use strict";

/**
 * Refuse npm publish of the committed 0.0.0 placeholder.
 *
 * prepublishOnly runs this before npm packs the tarball. The publish workflow
 * stamps GitVersion into package.json first, so a real release still passes.
 */

const { assertReleaseVersion } = require("./sync-npm-version.cjs");
const pkg = require("../package.json");

try {
  assertReleaseVersion(pkg.version);
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
}
