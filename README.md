# AIS WebMCP — manage WebMCP for any website

Make your website's capabilities clear to AI agents. `ais-webmcp` is the
framework-independent PyPI command for creating, validating and maintaining
WebMCP descriptions in the context of your website.

Use it with static sites, CMS websites, documentation portals or custom web
applications. Work with local JSON and YAML manifests, then connect the shared
browser helper to your website's own content and actions.

**DE:** Das frameworkunabhängige PyPI-Kommando, mit dem Sie WebMCP-Beschreibungen
für jede Art von Webseite erstellen, prüfen und sinnvoll pflegen können.

## Background

[Insight UI](https://pypi.org/project/insight-ui/) is our open-source,
WCAG-focused UI package, which we presented at the September meetup of the
Berlin Python User Group, hosted at our office. Our work on WebMCP grew out
of it as an extension, which is why we built insight-ui-webmcp first. At the
meetup, people asked whether we could offer it without the Django layer we
use for all our production-critical applications. That question is how
ais-webmcp came about: the same WebMCP core, without the framework. We look
forward to hearing what you think, and we warmly welcome contributions; see
[how to contribute](CONTRIBUTING.md).

## Packages at a glance

One browser runtime, `register.js`, is delivered three ways.

```mermaid
flowchart LR
  Core["ais-webmcp (PyPI)<br/>manifest, CLI, register.js"]
  Django["insight-ui-webmcp (PyPI)<br/>Django adapter"]
  NPM["@alpininsightsolutions/webmcp (npm)<br/>register.js only"]
  CDN["cdn.alpininsight.ai/ais-webmcp/vX.Y.Z/<br/>register.js"]
  Core --> Django
  Core --> NPM
  Core --> CDN
  Django --> S1["Django sites"]
  NPM --> S2["other websites (bundlers)"]
  CDN --> S3["script tag"]
```

- `ais-webmcp` on PyPI is the core: manifests, the CLI, and `register.js`.
  The Django adapter `insight-ui-webmcp` installs that core.
- `@alpininsightsolutions/webmcp` (coming soon) on npm is `register.js` only,
  for sites that bundle it.
- The CDN publishes `register.js` at `ais-webmcp/vX.Y.Z/` for a script tag.

The npm package and the CDN path are pending their first release and are not
live yet. The unscoped npm package `webmcp` is unrelated.

```bash
pip install ais-webmcp
ais-webmcp init --output manifest.yaml --static
ais-webmcp validate manifest.yaml
ais-webmcp list manifest.yaml
ais-webmcp doctor manifest.yaml --html index.html
ais-webmcp export manifest.yaml --output webmcp.manifest.json
ais-webmcp export manifest.yaml --kind tools --output tools.json
ais-webmcp export manifest.yaml --kind snippet --output snippet.html
ais-webmcp diff manifest.yaml webmcp.manifest.json
```

Python 3.12+; Django is not required. `doctor` and `status` report local
configuration and refuse remote URLs; browser support is verified separately.
CSP is noted and not rewritten. Origin Trial tokens are redacted to character
lengths. `export` can write a canonical manifest, a JSON tools list, or a
static snippet with no token. Existing files are protected unless you pass
`--force`. Consequential tools stay disabled in scaffolds until the host
explicitly enables and implements them.

## Output schemas

Declare a [Draft 2020-12 JSON Schema](https://json-schema.org/draft/2020-12)
for each tool result next to its input schema. The canonical key is
`outputSchema`; `output_schema` is an alias, and only one of them may be set.
`ToolSpec.output_schema` writes `outputSchema`.

`ais-webmcp validate` checks a present output schema: it must be a JSON object
and a valid [Draft 2020-12](https://json-schema.org/draft/2020-12) schema. An
invalid schema fails validation. Omitting the schema does not. The result stays
`ok`, the exit code stays 0, and each tool without a schema adds a finding:

<!-- markdownlint-disable MD013 -->

```json
{
  "path": "tools[0]",
  "code": "missing_output_schema",
  "severity": "low",
  "message": "missing outputSchema (also accepts output_schema). Optional for existing hosts; absence is a low-severity finding."
}
```

<!-- markdownlint-enable MD013 -->

Check engines can treat `missing_output_schema` as a low-severity finding.
Existing hosts keep validating until they declare output schemas. Text reports
print `finding:` lines and still start with `ok:` when there are no errors.

For Django and [Insight UI](https://pypi.org/project/insight-ui/) applications,
add the insight-ui-webmcp adapter. The core owns the shared schema and browser
runtime; the adapter uses the installed core rather than shipping a second
copy.

Development preview; the first public PyPI/CDN release is pending.

## Public npm package

The browser runtime is prepared as the public package
`@alpininsightsolutions/webmcp` (coming soon). Enterprise code never goes to
npm. The tarball is only the built `register.js`, its types, this README,
`LICENSE`, and `NOTICE` (`package.json` is included because npm always packs
it). A path under `enterprise/`, a path containing `webmcp_check`, or a `.env`
file fails the tarball guard.

|            |                                 |
| ---------- | ------------------------------- |
| PyPI / CLI | `ais-webmcp`                    |
| npm        | `@alpininsightsolutions/webmcp` |
| global     | `InsightUiWebmcp`               |
| CDN path   | `ais-webmcp/vX.Y.Z/`            |

```bash
npm install @alpininsightsolutions/webmcp
```

```ts
import InsightUiWebmcp from "@alpininsightsolutions/webmcp";

const status = InsightUiWebmcp.status();
if (status.supported) {
  await InsightUiWebmcp.registerFromManifest(
    {
      profile: "webpage",
      version: "1",
      tools: [
        {
          id: "search",
          name: "Search",
          description: "Search this page",
          inputSchema: {
            type: "object",
            properties: { q: { type: "string" } },
          },
        },
      ],
    },
    {
      search(input: { q?: string }) {
        return { results: [] };
      },
    },
  );
}
```

A `<script>` tag assigns that same object to `window.InsightUiWebmcp`.

The committed npm version is the `0.0.0` placeholder. Publish stamps
GitVersion's Major.Minor.Patch, the same version as the Python package, into
`package.json`. `npm run build:js` then injects that version into the
`InsightUiWebmcp` object in the built bundle. `prepublishOnly` rejects
`npm publish` while the version is still `0.0.0`. Publishing runs from this
repository: `.github/workflows/npm-publish.yml` calls the central reusable
workflow in `alpininsight/.github-private`
(`.github/workflows/npm-publish-reusable.yml`) with Trusted Publishing and
provenance. The trusted publisher is bound to `alpininsight/ais-webmcp`,
workflow `npm-publish.yml`, and environment `npm-ais-webmcp`. A release goes
out only with Peter's go. The first publish is the manual bootstrap.
One-time npmjs.com setup is in [docs/release.md](docs/release.md).

## Development

```bash
uv sync --locked --all-groups
npm ci
npm run check:js-build
npm test
uv run --locked pytest
uv run --locked pre-commit run --all-files
```

See [how to contribute](CONTRIBUTING.md).

Python 3.12–3.14 and Node 24 are checked in CI. Node 24 is the repo pin
(`.nvmrc` and `devEngines`); the published package does not set `engines`,
so installing the browser runtime does not warn on other Node versions.
Each release contains exactly
one wheel and one sdist. The browser runtime and schema publish under
`https://cdn.alpininsight.ai/ais-webmcp/vX.Y.Z/` after PyPI readback.
This namespace is a publication contract, not a claim that assets are live.

License: Apache-2.0 with NOTICE. Bundled dependencies retain their own licenses
in the generated runtime banner.

## Split provenance

Core history was extracted from
[insight-ui-webmcp at d6ead80843dbe42096791dd6688ed58a35dc3291](https://github.com/alpininsight/insight-ui-webmcp/tree/d6ead80843dbe42096791dd6688ed58a35dc3291).
See [the implementation tracker](https://github.com/alpininsight/insight-ui-webmcp/issues/63)
for the architecture decision, adapter/publisher/host migration and separate
release evidence. The original repository history and existing host pins are preserved.

### CDN verification after alias updates

The release readback checks all nine canonical objects (runtime, schema and
inventory under the immutable version, main and latest). Mutable aliases get a
shared 360-second convergence budget for the uploader's 300-second cache TTL.
Immutable mismatches and HTTP challenges fail immediately. CORS must contain
exactly one allowed origin value; duplicate response headers fail the gate.

Post-merge audit of Core #1 and adapter #60 (2026-10-11): green source checks
missed mutable-cache convergence and duplicate CORS headers. The owning Core
now tests both with a simulated clock and real multi-value HTTP headers. Before
future CDN changes, exercise stale mutable aliases as well as immutable defects;
keep package/license ownership in the Core when resolving split conflicts.

## CDN credential setup and promotion audit

The Core release caller follows the existing Insight UI/User/Brand organisation
contract: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `R2_ENDPOINT` map to the
central reusable uploader's `r2_access_key_id`, `r2_secret_access_key` and
`r2_endpoint` inputs. These existing organisation secrets must select
`alpininsight/ais-webmcp`; creating parallel `CDN_R2_*` credentials is unnecessary.
Never put values in source, issue comments or evidence.

The target bucket is `alpininsight-cdn`, with the owned prefix `ais-webmcp/`.
Secret availability alone neither verifies a working credential nor enables an
upload. The explicit release/CDN flags, exact reviewed Main source, matching
Core PyPI files, immutable clobber guard and nine canonical public GET checks
remain required. A control-plane CORS/domain check is separate from actual
object headers and bytes.

Post-merge lesson (2026-10-12): a green build-only release skips upload and cannot
prove its secret names exist. Compare caller secret names and selected-repository
metadata with the organisation contract before marking CDN prerequisites ready.
