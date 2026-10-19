"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../..");
const { allowedFiles, checkPackedFiles } = require("../../scripts/check-npm-pack.cjs");
const { assertReleaseVersion, stamp } = require("../../scripts/sync-npm-version.cjs");

const BUNDLE = "src/ais_webmcp/assets/register.js";
const TYPES = "src/ais_webmcp/assets/register.d.ts";

function pkg() {
  return JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
}

test("package metadata is the public scoped runtime", () => {
  const manifest = pkg();
  assert.equal(manifest.name, "@alpininsightsolutions/webmcp");
  assert.equal(manifest.version, "0.0.0");
  assert.equal(manifest.private, undefined);
  assert.equal(manifest.license, "Apache-2.0");
  assert.equal(manifest.repository.url, "git+https://github.com/alpininsight/ais-webmcp.git");
  assert.equal(manifest.homepage, "https://github.com/alpininsight/ais-webmcp#readme");
  assert.equal(manifest.bugs.url, "https://github.com/alpininsight/ais-webmcp/issues");
  assert.deepEqual(manifest.publishConfig, { access: "public", provenance: true });
  assert.equal(manifest.main, "./src/ais_webmcp/assets/register.js");
  assert.equal(manifest.types, "./src/ais_webmcp/assets/register.d.ts");
  assert.equal(manifest.exports["."].default, "./src/ais_webmcp/assets/register.js");
  assert.equal(manifest.exports["."].types, "./src/ais_webmcp/assets/register.d.ts");
  assert.deepEqual(manifest.files, [
    "src/ais_webmcp/assets/register.js",
    "src/ais_webmcp/assets/register.d.ts",
    "README.md",
    "LICENSE",
    "NOTICE",
  ]);
});

test("packed files must match the allowlist", () => {
  const allowed = allowedFiles(pkg());
  const ok = checkPackedFiles(
    ["package.json", "README.md", "LICENSE", "NOTICE", BUNDLE, TYPES],
    allowed,
  );
  assert.deepEqual(ok.missing, []);
  assert.deepEqual(ok.extra, []);
  assert.deepEqual(ok.forbidden, []);
  assert.deepEqual(ok.absent, []);

  const leaked = checkPackedFiles(
    [
      "package.json",
      "README.md",
      "LICENSE",
      "NOTICE",
      BUNDLE,
      TYPES,
      "enterprise/secret.js",
      "tools/webmcp_check/run.js",
      ".env",
      "src/.env.local",
    ],
    allowed,
  );
  assert.deepEqual(leaked.extra, [
    "enterprise/secret.js",
    "tools/webmcp_check/run.js",
    ".env",
    "src/.env.local",
  ]);
  assert.deepEqual(leaked.forbidden, leaked.extra);

  const stripped = checkPackedFiles(["package.json", "README.md", BUNDLE, TYPES], allowed);
  assert.deepEqual(stripped.missing, ["LICENSE", "NOTICE"]);
});

test("publish stamps the Python package version and refuses placeholders", () => {
  assert.throws(() => assertReleaseVersion("0.0.0"), /nonzero GitVersion/);
  assert.throws(() => assertReleaseVersion("0.1.0-alpha.1"), /nonzero GitVersion/);
  assert.throws(() => assertReleaseVersion("v0.1.0"), /nonzero GitVersion/);
  assertReleaseVersion("0.1.0");

  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ais-webmcp-npm-"));
  const assets = path.join(root, "src/ais_webmcp/assets");
  fs.mkdirSync(assets, { recursive: true });
  fs.writeFileSync(
    path.join(root, "package.json"),
    `${JSON.stringify({ name: "@alpininsightsolutions/webmcp", version: "0.0.0" }, null, 2)}\n`,
  );
  const runtime = path.join(assets, "register.js");
  fs.writeFileSync(runtime, 'var api={version:"0.0.0"};\n');
  const before = fs.readFileSync(runtime, "utf8");
  stamp(root, "1.2.3");
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version, "1.2.3");
  assert.equal(fs.readFileSync(runtime, "utf8"), before);
  assert.throws(() => stamp(root, "1.2.4"), /exactly once/);
});

test("built bundle version equals package.json", () => {
  const manifest = pkg();
  const bundle = fs.readFileSync(path.join(ROOT, BUNDLE), "utf8");
  const found = [...bundle.matchAll(/version\s*:\s*"([^"]*)"/g)].map((match) => match[1]);
  assert.deepEqual(found, [manifest.version]);
});

test("npm pack dry run stays inside the allowlist", () => {
  const result = spawnSync(process.execPath, ["scripts/check-npm-pack.cjs"], {
    cwd: ROOT,
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(result.stdout.trim().split("\n"), [
    "LICENSE",
    "NOTICE",
    "README.md",
    "package.json",
    TYPES,
    BUNDLE,
  ]);
});
