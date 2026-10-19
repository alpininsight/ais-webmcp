"use strict";

/**
 * Stamp the npm package with the Python package version.
 *
 * The committed package.json version and the register.js marker stay 0.0.0.
 * Publish calls this with GitVersion major_minor_patch, the same value
 * scripts/build_delivery.py uses for the Python distribution. There is no
 * second version source.
 */

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const RELEASE_VERSION =
  /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/;
const PACKAGE_PLACEHOLDER = /("version"\s*:\s*")0\.0\.0(")/;
const RUNTIME_PLACEHOLDER = /(version\s*:\s*)"0\.0\.0"/;

function assertReleaseVersion(version) {
  if (!RELEASE_VERSION.test(version) || version === "0.0.0") {
    throw new Error(
      "npm publish requires the nonzero GitVersion Major.Minor.Patch of the Python package",
    );
  }
}

function replaceOnce(text, pattern, replacement, label) {
  const matches = text.match(new RegExp(pattern, "g"));
  if (!matches || matches.length !== 1) {
    throw new Error(`${label} placeholder 0.0.0 must appear exactly once`);
  }
  return text.replace(pattern, replacement);
}

function stamp(root, version) {
  assertReleaseVersion(version);
  const packagePath = path.join(root, "package.json");
  const runtimePath = path.join(root, "src/ais_webmcp/assets/register.js");
  const packageText = replaceOnce(
    fs.readFileSync(packagePath, "utf8"),
    PACKAGE_PLACEHOLDER,
    `$1${version}$2`,
    "package.json version",
  );
  const runtimeText = replaceOnce(
    fs.readFileSync(runtimePath, "utf8"),
    RUNTIME_PLACEHOLDER,
    `$1"${version}"`,
    "runtime version marker",
  );
  fs.writeFileSync(packagePath, packageText);
  fs.writeFileSync(runtimePath, runtimeText);
}

function readVersion(argv) {
  const index = argv.indexOf("--version");
  const version = index >= 0 ? argv[index + 1] : "";
  if (!version) throw new Error("--version is required");
  return version;
}

module.exports = { assertReleaseVersion, stamp };

if (require.main === module) {
  try {
    stamp(ROOT, readVersion(process.argv));
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  }
}
