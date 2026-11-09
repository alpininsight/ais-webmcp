"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { assertProvenance } = require("../../scripts/assert-npm-release-version.cjs");
const { validateContext, validateStatement, verifyOptions, packageSubject } = require("../../scripts/release-candidate.cjs");

const sha = "a".repeat(40);
const env = {
  GITHUB_ACTIONS: "true", GITHUB_EVENT_NAME: "workflow_dispatch",
  GITHUB_REPOSITORY: "alpininsight/ais-webmcp", GITHUB_SERVER_URL: "https://github.com",
  GITHUB_REF: "refs/heads/main", GITHUB_SHA: sha,
  GITHUB_WORKFLOW_SHA: sha,
  GITHUB_WORKFLOW_REF: "alpininsight/ais-webmcp/.github/workflows/ci.yml@refs/heads/main",
  RUNNER_ENVIRONMENT: "github-hosted", GITHUB_RUN_ID: "123", GITHUB_RUN_ATTEMPT: "2",
};

test("local source publish requires one provenance option", () => {
  assert.throws(() => assertProvenance({}));
  assert.throws(() => assertProvenance({ npm_config_provenance: "false" }));
  assert.throws(() => assertProvenance({ npm_config_provenance: "true", npm_config_provenance_file: "bundle" }));
  assert.doesNotThrow(() => assertProvenance({ npm_config_provenance: "true" }));
  assert.doesNotThrow(() => assertProvenance({ npm_config_provenance_file: "bundle" }));
});

test("only the exact current Main and accepted stable tag can prepare", () => {
  assert.doesNotThrow(() => validateContext(env, "v1.2.3", sha, sha, sha));
  for (const bad of ["v0.0.0", "v01.2.3", "v1.2.3-rc.1"]) {
    assert.throws(() => validateContext(env, bad, sha, sha, sha));
  }
  for (const key of ["GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_WORKFLOW_REF", "RUNNER_ENVIRONMENT", "GITHUB_REPOSITORY"]) {
    assert.throws(() => validateContext({ ...env, [key]: "wrong" }, "v1.2.3", sha, sha, sha));
  }
  assert.throws(() => validateContext(env, "v1.2.3", sha, sha, "b".repeat(40)));
  assert.throws(() => validateContext(env, "v1.2.3", sha, "b".repeat(40), sha));
  assert.throws(() => validateContext({ ...env, SIGSTORE_ID_TOKEN: "configured" }, "v1.2.3", sha, sha, sha));
  assert.throws(() => validateContext({ ...env, NODE_AUTH_TOKEN: "configured" }, "v1.2.3", sha, sha, sha));
});

test("verifier requires certificate identity and certificate-bound source and run", () => {
  const options = verifyOptions({ sha, run: "123", attempt: "2" });
  assert.equal(options.certificateIssuer, "https://token.actions.githubusercontent.com");
  const identity = new RegExp(options.certificateIdentityURI);
  assert.match("https://github.com/alpininsight/ais-webmcp/.github/workflows/ci.yml@refs/heads/main", identity);
  assert.doesNotMatch("https://github.com/alpininsight/ais-webmcp/.github/workflows/ci.yml@refs/heads/other", identity);
  for (const n of [11, 12, 13, 14, 18, 19, 20, 21, 23]) assert.ok(options.certificateOIDs[`1.3.6.1.4.1.57264.1.${n}`]);
});

test("untrusted statement rejects missing proof and subject mismatch", () => {
  const subject = { name: "pkg:npm/%40alpininsightsolutions/webmcp@1.2.3", digest: { sha512: "abc" } };
  assert.throws(() => validateStatement({}, subject, { sha, run: "123", attempt: "2" }));
  const payload = { _type: "https://in-toto.io/Statement/v1", predicateType: "https://slsa.dev/provenance/v1", subject: [{ ...subject, name: "bad" }] };
  const bundle = { dsseEnvelope: { payloadType: "application/vnd.in-toto+json", payload: Buffer.from(JSON.stringify(payload)).toString("base64") } };
  assert.throws(() => validateStatement(bundle, subject, { sha, run: "123", attempt: "2" }), /subject mismatch/);
});

test("statement checks bind source, invocation and exact subject bytes", () => {
  const repository = "https://github.com/alpininsight/ais-webmcp";
  const subject = { name: "pkg:npm/%40alpininsightsolutions/webmcp@1.2.3", digest: { sha512: "abc" } };
  const statement = {
    _type: "https://in-toto.io/Statement/v1", predicateType: "https://slsa.dev/provenance/v1", subject: [subject],
    predicate: {
      buildDefinition: {
        buildType: "https://slsa-framework.github.io/github-actions-buildtypes/workflow/v1",
        externalParameters: { workflow: { path: ".github/workflows/ci.yml", ref: "refs/heads/main", repository } },
        internalParameters: { github: { event_name: "workflow_dispatch" } },
        resolvedDependencies: [{ uri: `git+${repository}@refs/heads/main`, digest: { gitCommit: sha } }],
      },
      runDetails: { builder: { id: "https://github.com/actions/runner/github-hosted" }, metadata: { invocationId: `${repository}/actions/runs/123/attempts/2` } },
    },
  };
  const pack = (data) => ({ dsseEnvelope: { payloadType: "application/vnd.in-toto+json", payload: Buffer.from(JSON.stringify(data)).toString("base64") } });
  const ctx = { sha, run: "123", attempt: "2" };
  assert.doesNotThrow(() => validateStatement(pack(statement), subject, ctx));
  assert.throws(() => validateStatement(pack(statement), { ...subject, digest: { sha512: "different" } }, ctx));
  assert.throws(() => validateStatement(pack(statement), subject, { ...ctx, attempt: "3" }));
  assert.throws(() => validateStatement(pack(statement), subject, { ...ctx, sha: "b".repeat(40) }));
});

test("final tarball guard checks bytes, file types and six-file allowlist", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "webmcp-candidate-test-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const root = path.join(dir, "package");
  fs.mkdirSync(path.join(root, "src/ais_webmcp/assets"), { recursive: true });
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "../../package.json")));
  pkg.version = "1.2.3";
  fs.writeFileSync(path.join(root, "package.json"), JSON.stringify(pkg));
  for (const name of ["README.md", "LICENSE", "NOTICE", "src/ais_webmcp/assets/register.js", "src/ais_webmcp/assets/register.d.ts"]) fs.writeFileSync(path.join(root, name), name);
  const files = ["package.json", ...pkg.files].map((name) => `package/${name}`);
  const archive = path.join(dir, "package.tgz");
  const pack = () => execFileSync("tar", ["-czf", archive, "-C", dir, ...files]);
  pack();
  const first = packageSubject(archive, "1.2.3");
  fs.appendFileSync(path.join(root, "README.md"), "changed");
  pack();
  assert.notEqual(packageSubject(archive, "1.2.3").digest.sha512, first.digest.sha512);
  fs.rmSync(path.join(root, "NOTICE"));
  fs.symlinkSync("LICENSE", path.join(root, "NOTICE"));
  pack();
  assert.throws(() => packageSubject(archive, "1.2.3"), /regular files/);
});
