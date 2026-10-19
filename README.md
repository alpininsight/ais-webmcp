# AIS WebMCP — manage WebMCP for any website

Make your website's capabilities clear to AI agents. `ais-webmcp` is the
framework-independent PyPI command for creating, validating and maintaining
WebMCP descriptions in the context of your website.

Use it with static sites, CMS websites, documentation portals or custom web
applications. Work with local JSON and YAML manifests, then connect the shared
browser helper to your website's own content and actions.

**DE:** Das frameworkunabhängige PyPI-Kommando, mit dem Sie WebMCP-Beschreibungen
für jede Art von Webseite erstellen, prüfen und sinnvoll pflegen können.

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

Declare a Draft 2020-12 JSON Schema for each tool result next to its input
schema. The canonical key is `outputSchema`; `output_schema` is an alias, and
only one of them may be set. `ToolSpec.output_schema` writes `outputSchema`.

`ais-webmcp validate` checks a present output schema: it must be a JSON object
and a valid Draft 2020-12 schema. An invalid schema fails validation. Omitting
the schema does not. The result stays `ok`, the exit code stays 0, and each
tool without a schema adds a finding:

```json
{
  "path": "tools[0]",
  "code": "missing_output_schema",
  "severity": "low",
  "message": "missing outputSchema (also accepts output_schema). Optional for existing hosts; absence is a low-severity finding."
}
```

Check engines can treat `missing_output_schema` as a low-severity finding.
Existing hosts keep validating until they declare output schemas. Text reports
print `finding:` lines and still start with `ok:` when there are no errors.

For Django and Insight UI applications, add the
[insight-ui-webmcp adapter](https://github.com/alpininsight/insight-ui-webmcp).
The core owns the shared schema and browser runtime; the adapter uses the
installed core rather than shipping a second copy.

Development preview; the first public PyPI/CDN release is pending.

## Development

```bash
uv sync --locked --all-groups
npm ci
npm run check:js-build
npm test
uv run --locked pytest
uv run --locked pre-commit run --all-files
```

Python 3.12–3.14 and Node 24 are checked in CI. Each release contains exactly
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
