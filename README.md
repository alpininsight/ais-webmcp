# ais-webmcp

Dev/CI client for WebMCP manifests. Console script: `ais-webmcp`.

This distribution does **not** depend on Django. It also ships the shared
`webmcp_manifest` module (schema, validator, tool dataclasses, built-in
profiles). That module is not a separate PyPI package.

```bash
pip install ais-webmcp
ais-webmcp validate manifest.yaml
ais-webmcp init --output manifest.yaml
ais-webmcp list manifest.yaml
python -m ais_webmcp validate manifest.yaml
```

`subscribe_newsletter` stays consequential and `enabled: false`. `doctor`,
`diff`, and `export` are not implemented yet.

The Django app is the separate distribution `insight-ui-webmcp` (import
`insight_ui_webmcp`). Docs may call that app `django-insight-ui-webmcp`.
