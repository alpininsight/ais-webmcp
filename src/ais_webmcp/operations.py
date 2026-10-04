"""Local, read-only host diagnostics and validated manifest operations."""

from __future__ import annotations

import difflib
import json
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from ais_webmcp.files import WriteResult, write_files
from ais_webmcp.scaffold import render_manifest
from ais_webmcp.validate import exit_code, load_manifest, render, validate_data, validate_path


class HostHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.origin_trial = False
        self.csp_self = None
        self.third_party = False

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "meta":
            equiv = (fields.get("http-equiv") or "").lower()
            if equiv == "origin-trial":
                self.origin_trial = bool(fields.get("content"))
            if equiv == "content-security-policy":
                directives = (fields.get("content") or "").split(";")
                policies = {d.split()[0]: d.split()[1:] for d in directives if d.split()}
                sources = policies.get("script-src", policies.get("default-src", []))
                self.csp_self = "'self'" in sources
        if tag == "script" and fields.get("src"):
            self.third_party |= bool(urlsplit(fields["src"]).netloc)


def doctor(
    path: Path, *, html: Path | None = None, extra_profiles=(), origin_trial_configured=False
):
    """Return configuration evidence only. Never include HTML/token contents."""
    checked = validate_path(path, extra_profiles=extra_profiles)
    rows = [{"check": "manifest", "status": "ok" if checked.ok else "error"}]
    helper = resources.files("ais_webmcp").joinpath("assets/register.js")
    rows.append({"check": "packaged_helper", "status": "ok" if helper.is_file() else "error"})
    parsed = HostHTML()
    code = exit_code([checked])
    if html is not None:
        try:
            parsed.feed(html.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            rows.append({"check": "host_html", "status": "error"})
            code = 2
    rows.extend(
        [
            {
                "check": "origin_trial_configuration",
                "status": "present"
                if parsed.origin_trial or origin_trial_configured
                else "warning",
            },
            {"check": "csp_same_origin", "status": "ok" if parsed.csp_self is True else "warning"},
            {
                "check": "third_party_scripts",
                "status": "warning" if parsed.third_party else "none_detected",
            },
            {"check": "browser_support", "status": "unverified"},
        ]
    )
    if not helper.is_file():
        code = max(code, 1)
    return {
        "checks": rows,
        "exit_code": code,
        "note": "document.modelContext is browser-only; local configuration is not browser or deployment evidence.",
    }, code


def canonical_manifest(path: Path, *, extra_profiles=()):
    data, fatal = load_manifest(path)
    result = fatal or validate_data(data, source=str(path), extra_profiles=extra_profiles)
    if result.ok:
        for tool in data["tools"]:
            for alias in ("parameters", "input_schema"):
                if alias in tool:
                    tool["inputSchema"] = tool.pop(alias)
    return data, result


def export_manifest(source: Path, target: Path, *, force=False, extra_profiles=()) -> WriteResult:
    data, result = canonical_manifest(source, extra_profiles=extra_profiles)
    if not result.ok:
        return WriteResult(exit_code([result]), render([result], "text"))
    try:
        text = render_manifest(data, target.suffix)
    except (RuntimeError, ValueError) as exc:
        return WriteResult(2, f"error: {exc}\n")
    return write_files({target: text}, force=force)


def diff_manifests(left: Path, right: Path, *, extra_profiles=()):
    a, ar = canonical_manifest(left, extra_profiles=extra_profiles)
    b, br = canonical_manifest(right, extra_profiles=extra_profiles)
    if not ar.ok or not br.ok:
        return render([ar, br], "text"), exit_code([ar, br])
    lines = [json.dumps(x, indent=2, sort_keys=True).splitlines(keepends=True) for x in (a, b)]
    delta = "".join(difflib.unified_diff(*lines, fromfile=str(left), tofile=str(right)))
    return delta, int(bool(delta))
