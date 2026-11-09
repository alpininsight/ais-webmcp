"use strict";

// The generator and verifier are provided by the pinned npm distribution.
const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { assertReleaseVersion } = require("./sync-npm-version.cjs");
const { checkPackedFiles } = require("./check-npm-pack.cjs");

const repo = "alpininsight/ais-webmcp";
const repository = `https://github.com/${repo}`;
const workflow = ".github/workflows/ci.yml";
const workflowRef = `${repository}/${workflow}@refs/heads/main`;
const allowed = new Set([
  "package.json", "README.md", "LICENSE", "NOTICE",
  "src/ais_webmcp/assets/register.js", "src/ais_webmcp/assets/register.d.ts",
]);

function requireThat(condition, message) {
  if (!condition) throw new Error(message);
}

function derUtf8(value) {
  const data = Buffer.from(value, "utf8");
  requireThat(data.length < 256, "certificate value too long");
  return Buffer.concat([Buffer.from(data.length < 128 ? [12, data.length] : [12, 129, data.length]), data]);
}

function validateContext(env, tag, head, main, tagCommit) {
  requireThat(!Object.keys(env).some((key) => /^(?:SIGSTORE_ID_TOKEN|NODE_AUTH_TOKEN|NPM_TOKEN|npm_config_.*(?:_authtoken|_auth|_password))$/i.test(key) && env[key]), "unexpected credential configuration");
  requireThat(env.GITHUB_ACTIONS === "true" && env.GITHUB_EVENT_NAME === "workflow_dispatch", "manual GitHub Actions required");
  requireThat(env.GITHUB_REPOSITORY === repo && env.GITHUB_SERVER_URL === "https://github.com", "repository mismatch");
  requireThat(env.GITHUB_REF === "refs/heads/main" && env.GITHUB_WORKFLOW_REF === `${repo}/${workflow}@refs/heads/main`, "workflow or ref mismatch");
  requireThat(env.RUNNER_ENVIRONMENT === "github-hosted", "GitHub-hosted runner required");
  requireThat(/^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/.test(tag), "invalid stable tag");
  assertReleaseVersion(tag.slice(1));
  requireThat(/^[0-9a-f]{40}$/.test(env.GITHUB_SHA) && env.GITHUB_SHA === head && head === main && head === tagCommit, "source, Main and tag must match");
  requireThat(env.GITHUB_WORKFLOW_SHA === env.GITHUB_SHA, "workflow source mismatch");
  requireThat(/^[1-9]\d*$/.test(env.GITHUB_RUN_ID) && /^[1-9]\d*$/.test(env.GITHUB_RUN_ATTEMPT), "invalid run identity");
}

function context(env, tag) {
  const git = (...args) => execFileSync("git", args, { encoding: "utf8" }).trim();
  validateContext(env, tag, git("rev-parse", "HEAD"), git("rev-parse", "origin/main"), git("rev-parse", `refs/tags/${tag}^{commit}`));
  return {
    sha: env.GITHUB_SHA, tag, run: env.GITHUB_RUN_ID, attempt: env.GITHUB_RUN_ATTEMPT,
    tree: git("rev-parse", "HEAD^{tree}"),
  };
}

function packageSubject(tarball, version) {
  assertReleaseVersion(version);
  const bytes = fs.readFileSync(tarball);
  const paths = execFileSync("tar", ["-tzf", tarball], { encoding: "utf8" }).trim().split("\n");
  requireThat(paths.length === allowed.size && new Set(paths).size === paths.length && paths.every((p) => p.startsWith("package/")), "unexpected tar entries");
  const entries = execFileSync("tar", ["-tvzf", tarball], { encoding: "utf8" }).trim().split("\n");
  requireThat(entries.length === allowed.size && entries.every((entry) => entry.startsWith("-")), "tarball must contain only regular files");
  const checked = checkPackedFiles(paths, allowed);
  requireThat(!checked.missing.length && !checked.extra.length && !checked.absent.length && !checked.forbidden.length, "tarball allowlist mismatch");
  const pkg = JSON.parse(execFileSync("tar", ["-xOzf", tarball, "package/package.json"], { encoding: "utf8" }));
  requireThat(pkg.name === "@alpininsightsolutions/webmcp" && pkg.version === version && pkg.license === "Apache-2.0" && pkg.private !== true, "tarball manifest mismatch");
  requireThat(pkg.repository?.url === `git+${repository}.git` && pkg.publishConfig?.access === "public" && !("provenance" in pkg.publishConfig), "tarball publication metadata mismatch");
  return { name: `pkg:npm/%40alpininsightsolutions/webmcp@${version}`, digest: { sha512: crypto.createHash("sha512").update(bytes).digest("hex") } };
}

function validateStatement(bundle, subject, ctx) {
  requireThat(bundle?.dsseEnvelope?.payloadType === "application/vnd.in-toto+json", "invalid DSSE payload type");
  const statement = JSON.parse(Buffer.from(bundle.dsseEnvelope.payload, "base64").toString("utf8"));
  requireThat(statement._type === "https://in-toto.io/Statement/v1" && statement.predicateType === "https://slsa.dev/provenance/v1", "unexpected statement type");
  requireThat(Array.isArray(statement.subject) && statement.subject.length === 1 && statement.subject[0].name === subject.name && statement.subject[0].digest?.sha512 === subject.digest.sha512, "subject mismatch");
  const definition = statement.predicate?.buildDefinition;
  const details = statement.predicate?.runDetails;
  requireThat(definition?.buildType === "https://slsa-framework.github.io/github-actions-buildtypes/workflow/v1", "build type mismatch");
  const wf = definition.externalParameters?.workflow;
  requireThat(wf?.path === workflow && wf.ref === "refs/heads/main" && wf.repository === repository, "workflow statement mismatch");
  requireThat(definition.internalParameters?.github?.event_name === "workflow_dispatch", "event mismatch");
  requireThat(definition.resolvedDependencies?.length === 1 && definition.resolvedDependencies[0].uri === `git+${repository}@refs/heads/main` && definition.resolvedDependencies[0].digest?.gitCommit === ctx.sha, "source statement mismatch");
  requireThat(details?.builder?.id === "https://github.com/actions/runner/github-hosted" && details.metadata?.invocationId === `${repository}/actions/runs/${ctx.run}/attempts/${ctx.attempt}`, "builder or invocation mismatch");
}

function verifyOptions(ctx) {
  const oid = "1.3.6.1.4.1.57264.1.";
  return {
    certificateIssuer: "https://token.actions.githubusercontent.com",
    certificateIdentityURI: `^${workflowRef.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`,
    certificateOIDs: {
      [oid + "11"]: derUtf8("github-hosted"),
      [oid + "12"]: derUtf8(repository),
      [oid + "13"]: derUtf8(ctx.sha),
      [oid + "14"]: derUtf8("refs/heads/main"),
      [oid + "18"]: derUtf8(workflowRef),
      [oid + "19"]: derUtf8(ctx.sha),
      [oid + "20"]: derUtf8("workflow_dispatch"),
      [oid + "21"]: derUtf8(`${repository}/actions/runs/${ctx.run}/attempts/${ctx.attempt}`),
      [oid + "23"]: derUtf8("npm-ais-webmcp"),
    },
  };
}

async function main() {
  const [command, tag, tarball, output, sha, run, attempt] = process.argv.slice(2);
  requireThat((command === "generate" || command === "verify") && tag && tarball && output, "usage: generate TAG TARBALL OUTPUT_DIR | verify TAG TARBALL BUNDLE SHA RUN ATTEMPT");
  requireThat(/^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/.test(tag), "invalid stable tag");
  const ctx = command === "generate" ? context(process.env, tag) : { sha, run, attempt };
  requireThat(/^[0-9a-f]{40}$/.test(ctx.sha || "") && /^[1-9]\d*$/.test(ctx.run || "") && /^[1-9]\d*$/.test(ctx.attempt || ""), "invalid expected identity");
  const subject = packageSubject(tarball, tag.slice(1));
  const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
  const npmDir = path.join(npmRoot, "npm");
  requireThat(require(path.join(npmDir, "package.json")).version === "12.2.2", "npm 12.2.2 required");
  const { generateProvenance } = require(path.join(npmDir, "node_modules/libnpmpublish/lib/provenance.js"));
  const sigstore = require(path.join(npmDir, "node_modules/sigstore"));
  const bundle = command === "generate"
    ? await generateProvenance([subject], { legacyCompatibility: true })
    : JSON.parse(fs.readFileSync(output, "utf8"));
  await sigstore.verify(bundle, verifyOptions(ctx));
  validateStatement(bundle, subject, ctx);
  if (command === "verify") return;
  fs.mkdirSync(output, { recursive: true });
  const bundleBytes = Buffer.from(JSON.stringify(bundle) + "\n");
  fs.writeFileSync(path.join(output, "provenance.sigstore.json"), bundleBytes, { flag: "wx" });
  fs.copyFileSync(tarball, path.join(output, "package.tgz"), fs.constants.COPYFILE_EXCL);
  const ci = JSON.parse(fs.readFileSync(path.join(output, "main-ci.json"), "utf8"));
  requireThat(ci.source_sha === ctx.sha, "CI receipt source mismatch");
  const receipt = { ...ctx, ref: "refs/heads/main", repository, workflow: workflowRef, subject, bundle_sha256: crypto.createHash("sha256").update(bundleBytes).digest("hex"), main_ci: ci };
  fs.writeFileSync(path.join(output, "receipt.json"), JSON.stringify(receipt, null, 2) + "\n", { flag: "wx" });
}

module.exports = { validateContext, validateStatement, verifyOptions, packageSubject };
if (require.main === module) main().catch((error) => { console.error(error.message); process.exitCode = 1; });
