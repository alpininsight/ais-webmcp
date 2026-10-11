/**
 * Third-party licenses in the standalone register.js (local asset and the
 * byte-identical CDN copy). Every bundled npm package must carry its full
 * license text in the leading banner and be listed in NOTICE.
 * Run: node --test tests/js/licenses.test.js
 */
"use strict";

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../..");
const REGISTER_JS = path.join(
  ROOT,
  "src/ais_webmcp/assets/register.js",
);
const source = fs.readFileSync(REGISTER_JS, "utf8");
const banner = source.slice(0, source.indexOf("*/"));
// pytest also runs these tests without `npm ci`; the node_modules comparison
// then runs in the npm job (alongside `npm run check:js-build`) only.
const NODE_MODULES = path.join(ROOT, "node_modules");
const noNodeModules =
  !fs.existsSync(NODE_MODULES) && "node_modules not installed (npm ci)";
const listed = [...banner.matchAll(/^== (\S+)@(\S+) \((\S+)\) ==$/gm)].map(
  ([, name, version, license]) => ({ name, version, license }),
);

function licenseText(name) {
  const root = path.join(ROOT, "node_modules", name);
  const file = fs
    .readdirSync(root)
    .find((f) => /^licen[cs]e(\.(md|txt))?$/i.test(f));
  assert.ok(file, `${name} has no LICENSE file`);
  return fs.readFileSync(path.join(root, file), "utf8").trim();
}

describe("register.js third-party licenses", () => {
  it("lists ajv and fast-deep-equal", () => {
    const names = listed.map((p) => p.name);
    assert.ok(names.includes("ajv"), names.join(","));
    assert.ok(names.includes("fast-deep-equal"), names.join(","));
  });

  it("each section carries a license text", () => {
    const sections = banner.split(/^== .+ ==$/m).slice(1);
    assert.equal(sections.length, listed.length);
    listed.forEach((p, i) => {
      if (p.license === "MIT")
        assert.match(sections[i], /Permission is hereby granted/, p.name);
      else assert.ok(sections[i].trim().length > 200, p.name);
    });
  });

  it(
    "embeds each bundled package's full license text and version",
    {
      skip: noNodeModules,
    },
    () => {
      for (const p of listed) {
        const pkg = JSON.parse(
          fs.readFileSync(
            path.join(ROOT, "node_modules", p.name, "package.json"),
            "utf8",
          ),
        );
        assert.equal(p.version, pkg.version, p.name);
        assert.equal(p.license, pkg.license, p.name);
        assert.ok(banner.includes(licenseText(p.name)), p.name);
      }
    },
  );

  it("every bundled package is named in the core NOTICE", () => {
    for (const notice of [
      "NOTICE",
    ]) {
      const text = fs.readFileSync(path.join(ROOT, notice), "utf8");
      for (const p of listed)
        assert.ok(text.includes(p.name), `${notice}: ${p.name}`);
    }
  });
});
