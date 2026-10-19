"use strict";

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const PACKAGE_NAME = "@alpininsightsolutions/webmcp";
const REQUIRED = ["LICENSE", "NOTICE"];
const FORBIDDEN = [
  /(^|\/)enterprise\//,
  /webmcp_check/,
  /(^|\/)\.env(?:\.|\/|$)/,
];

function normalizePackedPath(file) {
  return String(file)
    .replace(/\\/g, "/")
    .replace(/^\.\//, "")
    .replace(/^package\//, "");
}

function allowedFiles(pkg) {
  return new Set(["package.json", ...(pkg.files || [])]);
}

function checkPackedFiles(paths, allowed) {
  const files = paths.map(normalizePackedPath);
  return {
    files,
    missing: REQUIRED.filter((name) => !files.includes(name)),
    forbidden: files.filter((file) =>
      FORBIDDEN.some((pattern) => pattern.test(file)),
    ),
    extra: files.filter((file) => !allowed.has(file)),
    absent: [...allowed].filter((file) => !files.includes(file)),
  };
}

function parsePackJson(stdout) {
  const start = stdout.indexOf("[");
  const end = stdout.lastIndexOf("]");
  if (start < 0 || end < start) {
    throw new Error("npm pack --dry-run --json did not return a file list");
  }
  const payload = JSON.parse(stdout.slice(start, end + 1));
  if (
    !Array.isArray(payload) ||
    payload.length !== 1 ||
    !Array.isArray(payload[0].files)
  ) {
    throw new Error("unexpected npm pack JSON");
  }
  return payload[0];
}

function assertPublicPackage(pkg) {
  if (pkg.name !== PACKAGE_NAME) {
    throw new Error(`unexpected package name ${pkg.name}`);
  }
  if (pkg.private === true) {
    throw new Error("refusing to pack a private package");
  }
}

function reportFailure(result) {
  const problems = [];
  if (result.missing.length) {
    problems.push(`missing ${result.missing.join(", ")}`);
  }
  if (result.extra.length) {
    problems.push(`outside allowlist: ${result.extra.join(", ")}`);
  }
  if (result.absent.length) {
    problems.push(`allowlist file not packed: ${result.absent.join(", ")}`);
  }
  if (result.forbidden.length) {
    problems.push(`forbidden path: ${result.forbidden.join(", ")}`);
  }
  throw new Error(problems.join("; "));
}

function main() {
  const pkg = JSON.parse(
    fs.readFileSync(path.join(ROOT, "package.json"), "utf8"),
  );
  assertPublicPackage(pkg);
  const env = { ...process.env };
  delete env.NODE_AUTH_TOKEN;
  delete env.NPM_TOKEN;
  const stdout = execFileSync("npm", ["pack", "--dry-run", "--json"], {
    cwd: ROOT,
    encoding: "utf8",
    env,
    stdio: ["ignore", "pipe", "inherit"],
  });
  const packed = parsePackJson(stdout);
  const result = checkPackedFiles(
    packed.files.map((file) => file.path),
    allowedFiles(pkg),
  );
  if (
    result.missing.length ||
    result.forbidden.length ||
    result.extra.length ||
    result.absent.length
  ) {
    reportFailure(result);
  }
  process.stdout.write(`${[...result.files].sort().join("\n")}\n`);
}

module.exports = {
  FORBIDDEN,
  allowedFiles,
  checkPackedFiles,
  normalizePackedPath,
  parsePackJson,
};

if (require.main === module) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  }
}
