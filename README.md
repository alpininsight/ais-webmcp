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
