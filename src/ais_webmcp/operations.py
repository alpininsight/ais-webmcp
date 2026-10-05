"""Local, read-only host diagnostics and validated manifest operations."""

from __future__ import annotations

import difflib
import json
import re
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlparse, urlsplit

from ais_webmcp.files import WriteResult, write_files
from ais_webmcp.listing import list_path
from ais_webmcp.scaffold import render_manifest
from ais_webmcp.validate import (
    ValidationResult,
    exit_code,
    load_manifest,
    render,
    validate_data,
    validate_path,
)

REMOTE_MESSAGE = (
    "refusing to fetch a remote URL. "
    "Pass a local project path or local files. "
    "This command does not fetch a production page and does not control a browser."
)

_EXPORT_KINDS = ("manifest", "tools", "snippet")
_HEADER_VALUE = re.compile(
    r"(?im)(?:^|[\s;{])(?:add_header[ \t]+)?origin-trial[ \t]*[:=][ \t]*([^\s;\"'#]+)"
)
_CSP_HEADER = re.compile(
    r"(?im)content-security-policy(?:-report-only)?[ \t]*[:=][ \t]*[\"']?([^\"'\n]+)"
)
_IGNORED_HEADER_VALUES = frozenset({"header", "tag", "meta"})


class HostHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.origin_trial = False
        self.origin_trial_lengths: list[int] = []
        self.csp_self = None
        self.csp_note = "not detected in scanned HTML (not rewritten)"
        self.third_party = False
        self.third_party_hosts: list[str] = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "meta":
            equiv = (fields.get("http-equiv") or "").lower()
            if equiv == "origin-trial":
                content = fields.get("content") or ""
                if content:
                    self.origin_trial = True
                    self.origin_trial_lengths.append(len(content))
            if equiv == "content-security-policy" and fields.get("content"):
                self._note_csp(fields["content"])
        if tag == "script" and fields.get("src"):
            host = urlsplit(fields["src"]).hostname
            if host:
                self.third_party = True
                if host not in self.third_party_hosts:
                    self.third_party_hosts.append(host)

    def note_csp_policy(self, policy: str) -> None:
        """Record a CSP note. The policy text itself is not retained."""
        self._note_csp(policy)

    def _note_csp(self, policy: str) -> None:
        directives = policy.split(";")
        policies = {
            part.split()[0].lower(): part.split()[1:] for part in directives if part.split()
        }
        sources = policies.get("script-src", policies.get("default-src", []))
        if not sources and "script-src" not in policies and "default-src" not in policies:
            self.csp_self = False if self.csp_self is None else self.csp_self
            self.csp_note = "CSP present without script-src; default-src may apply (not rewritten)"
            return
        if "'self'" in sources:
            self.csp_self = True
            self.csp_note = "script-src includes 'self' (same-origin helper is the webpage pattern; not rewritten)"
            return
        self.csp_self = False
        self.csp_note = (
            "script-src does not include 'self' and may block the helper (not rewritten)"
        )


def resolve_local_target(raw: str) -> tuple[Path | None, str | None]:
    """Map a CLI argument to a local path.

    ``http`` and ``https`` are refused. ``file`` URLs are local paths.
    The error string is safe to print and does not repeat the remote target.
    """
    text = raw.strip()
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return None, REMOTE_MESSAGE
    if lowered.startswith("file://"):
        parsed = urlparse(text)
        if parsed.netloc not in {"", "localhost"}:
            return None, REMOTE_MESSAGE
        return Path(unquote(parsed.path)), None
    return Path(text), None


def _as_local(value: Path | str | None) -> tuple[Path | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, Path):
        return value, None
    return resolve_local_target(value)


def _header_token_lengths(text: str) -> list[int]:
    """Lengths of Origin-Trial header values. Values are discarded."""
    lengths: list[int] = []
    for match in _HEADER_VALUE.finditer(text):
        value = match.group(1).strip()
        if value and value.lower() not in _IGNORED_HEADER_VALUES:
            lengths.append(len(value))
    return lengths


BROWSER_STATUS_HINT = (
    "Check in the page with InsightUiWebmcp.status(): "
    "ok, no-origin-trial-meta or no-model-context. The token value is never reported."
)


def _refused(message: str) -> tuple[dict, int]:
    report = {
        "checks": [{"check": "target", "status": "error", "detail": message}],
        "exit_code": 2,
        "note": "document.modelContext is browser-only; local configuration is not browser or deployment evidence.",
    }
    return report, 2


def doctor(
    path: Path | str,
    *,
    html: Path | str | None = None,
    extra_profiles=(),
    origin_trial_configured=False,
):
    """Return configuration evidence only. Never include HTML or token contents."""
    checked_path, refused = _as_local(path)
    if refused or checked_path is None:
        return _refused(refused or REMOTE_MESSAGE)
    html_path, html_refused = _as_local(html)
    if html_refused:
        return _refused(html_refused)
    checked = validate_path(checked_path, extra_profiles=extra_profiles)
    rows = [{"check": "manifest", "status": "ok" if checked.ok else "error"}]
    helper = resources.files("ais_webmcp").joinpath("assets/register.js")
    rows.append({"check": "packaged_helper", "status": "ok" if helper.is_file() else "error"})
    parsed = HostHTML()
    header_lengths: list[int] = []
    code = exit_code([checked])
    if html_path is not None:
        try:
            text = html_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            rows.append({"check": "host_html", "status": "error"})
            code = 2
        else:
            parsed.feed(text)
            header_lengths = _header_token_lengths(text)
            for match in _CSP_HEADER.finditer(text):
                parsed.note_csp_policy(match.group(1).strip())
    lengths = [*parsed.origin_trial_lengths, *header_lengths]
    origin_bits: list[str] = []
    if lengths:
        shown = ", ".join(str(item) for item in lengths[:8])
        origin_bits.append(
            f"{len(lengths)} configured value(s), character lengths {shown} (token redacted)"
        )
    if origin_trial_configured:
        origin_bits.append("setting configured (value not read, token not printed)")
    origin_row = {
        "check": "origin_trial_configuration",
        "status": "present"
        if parsed.origin_trial or header_lengths or origin_trial_configured
        else "warning",
    }
    if origin_bits:
        origin_row["detail"] = "; ".join(origin_bits)
    third_row = {
        "check": "third_party_scripts",
        "status": "warning" if parsed.third_party else "none_detected",
    }
    if parsed.third_party_hosts:
        shown_hosts = ", ".join(parsed.third_party_hosts[:8])
        third_row["detail"] = f"third-party script host(s): {shown_hosts} (not rewritten)"
    rows.extend(
        [
            origin_row,
            {
                "check": "csp_same_origin",
                "status": "ok" if parsed.csp_self is True else "warning",
                "detail": parsed.csp_note,
            },
            third_row,
            {
                "check": "browser_support",
                "status": "unverified",
                "detail": BROWSER_STATUS_HINT,
            },
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


def _snippet(manifest_name: str) -> str:
    return (
        "<!-- ais-webmcp export snippet. No Origin Trial token. Does not register tools. -->\n"
        "<!--\n"
        '  Origin Trial is a host concern. Add a meta http-equiv="origin-trial" tag,\n'
        "  or an Origin-Trial response header, only where the token is configured.\n"
        "  This snippet never includes a token.\n"
        "-->\n"
        '<script src="register.js" defer data-insight-ui-webmcp="register"></script>\n'
        "<!--\n"
        f"  Manifest: {manifest_name}\n"
        "  document.modelContext is a browser runtime feature-detect. This CLI cannot see the browser.\n"
        "  Spec: https://webmachinelearning.github.io/webmcp/\n"
        "  Enabled flags are copied from the manifest. subscribe_newsletter stays off unless that file enables it.\n"
        "-->\n"
    )


def export_manifest(
    source: Path,
    target: Path,
    *,
    force=False,
    extra_profiles=(),
    kind: str = "manifest",
) -> WriteResult:
    """Export a canonical manifest, a JSON tools list, or a static snippet.

    The snippet never embeds an Origin Trial token and does not register tools.
    """
    if kind not in _EXPORT_KINDS:
        return WriteResult(2, f"error: unknown export kind {kind!r}\n")
    if kind == "tools":
        listed = list_path(source, extra_profiles=extra_profiles)
        if isinstance(listed, ValidationResult):
            code = 2 if listed.fatal else 1
            return WriteResult(code, render([listed], "text"))
        text = json.dumps(listed.to_dict(), indent=2, ensure_ascii=False) + "\n"
        return write_files({target: text}, force=force)
    data, result = canonical_manifest(source, extra_profiles=extra_profiles)
    if not result.ok:
        return WriteResult(exit_code([result]), render([result], "text"))
    if kind == "snippet":
        return write_files({target: _snippet(source.name)}, force=force)
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
