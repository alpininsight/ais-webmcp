"""Validate WebMCP manifests against the shared JSON Schema.

This module must not import Django. Static hosts and ``ais-webmcp validate`` use it
directly; ``manage.py webmcp_validate`` calls the same functions. The client distribution installs jsonschema and PyYAML normally, without Django.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

# Recorded on every result. The validator does not execute tools (issue #11).
LIFECYCLE_NOTE = "unregister is AbortController / { signal } on registerTool, not unregisterTool"

SCHEMA_KEYS = ("inputSchema", "parameters", "input_schema")
ALLOWED_ANNOTATIONS = frozenset(
    {"readOnlyHint", "consequentialHint", "untrustedContentHint", "debugging"}
)
# Schema validators that restated our semantic messages. oneOf context is noisy
# when the missing / ambiguous / non-object schema key is already reported.
_SKIP_SCHEMA_VALIDATORS = frozenset({"oneOf"})
_SEMANTIC_REQUIRED = frozenset(
    {
        "name",
        "description",
        "enabled",
        "inputSchema",
        "parameters",
        "input_schema",
        "profile",
        "version",
        "tools",
    }
)

_YAML_SUFFIXES = {".yaml", ".yml"}
_JSON_SUFFIXES = {".json"}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One schema or semantic failure."""

    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome for a single manifest document or file."""

    ok: bool
    source: str
    issues: tuple[ValidationIssue, ...]
    notes: tuple[str, ...] = (LIFECYCLE_NOTE,)
    fatal: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly result. ``notes`` always includes the abort lifecycle note."""
        return {
            "ok": self.ok,
            "path": self.source,
            "fatal": self.fatal,
            "issues": [{"path": issue.path, "message": issue.message} for issue in self.issues],
            "notes": list(self.notes),
        }


def schema_path() -> Path:
    """Return the packaged JSON Schema file (the manifest SSOT)."""
    return Path(__file__).resolve().parent / "schema" / "webmcp-manifest.schema.json"


@lru_cache(maxsize=1)
def _load_schema_cached() -> dict[str, Any]:
    raw = schema_path().read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("WebMCP manifest schema must be a JSON object")
    try:
        Draft202012Validator.check_schema(data)
    except SchemaError as exc:
        raise RuntimeError(
            f"WebMCP manifest schema is not a valid Draft 2020-12 schema: {exc}"
        ) from exc
    return data


def load_schema() -> dict[str, Any]:
    """Return a deep copy of the manifest JSON Schema."""
    return copy.deepcopy(_load_schema_cached())


def builtin_profiles() -> tuple[str, ...]:
    """Profile names published in the schema enum (SSOT, not the Django registry)."""
    enum = load_schema()["properties"]["profile"]["enum"]
    if (
        not isinstance(enum, list)
        or not enum
        or not all(isinstance(item, str) and item for item in enum)
    ):
        raise RuntimeError("manifest schema profile.enum must list non-empty strings")
    return tuple(enum)


def _tool_name_pattern() -> re.Pattern[str]:
    pattern = load_schema()["$defs"]["tool"]["properties"]["id"]["pattern"]
    if not isinstance(pattern, str) or not pattern:
        raise RuntimeError("manifest schema tool id pattern is missing")
    return re.compile(pattern)


def _format_path(path: Any) -> str:
    out = ""
    for part in path:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += ("." if out else "") + str(part)
    return out or "$"


def _issue(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(path=path, message=message)


def _tool_token(tool: dict[str, Any], index: int) -> str:
    ident = tool.get("id")
    if isinstance(ident, str) and ident:
        return ident
    name = tool.get("name")
    if isinstance(name, str) and name:
        return name
    return f"#{index}"


def _semantic_issues(data: Any, allowed_profiles: tuple[str, ...]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(data, dict):
        return [_issue("$", "manifest must be a JSON object")]

    profile = data.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        issues.append(_issue("profile", "missing profile"))
    elif profile not in allowed_profiles:
        known = ", ".join(allowed_profiles) or "(none)"
        issues.append(_issue("profile", f"unknown profile {profile!r} (known: {known})"))

    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, str) or not version.strip():
        issues.append(_issue("version", "version must be a non-empty string (quote it in YAML)"))

    tools = data.get("tools")
    if not isinstance(tools, list):
        issues.append(_issue("tools", "tools must be an array"))
        return issues

    name_re = _tool_name_pattern()
    seen: dict[str, int] = {}
    for index, tool in enumerate(tools):
        prefix = f"tools[{index}]"
        if not isinstance(tool, dict):
            issues.append(_issue(prefix, "tool must be an object"))
            continue

        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(_issue(f"{prefix}.name", "missing name"))

        description = tool.get("description")
        if not isinstance(description, str) or not description.strip():
            issues.append(_issue(f"{prefix}.description", "missing description"))

        present = [key for key in SCHEMA_KEYS if key in tool]
        if not present:
            issues.append(
                _issue(
                    prefix,
                    "missing inputSchema (also accepts parameters or input_schema, not more than one)",
                )
            )
        elif len(present) > 1:
            joined = ", ".join(present)
            issues.append(
                _issue(
                    prefix,
                    f"ambiguous schema keys ({joined}); keep only one of inputSchema, parameters, input_schema",
                )
            )
        else:
            key = present[0]
            if not isinstance(tool[key], dict):
                issues.append(_issue(f"{prefix}.{key}", f"{key} must be a JSON object"))
            else:
                try:
                    Draft202012Validator.check_schema(tool[key])
                except SchemaError as exc:
                    issues.append(
                        _issue(
                            f"{prefix}.{key}", f"invalid Draft 2020-12 input schema: {exc.message}"
                        )
                    )

        ident = tool.get("id")
        if "id" in tool:
            if not isinstance(ident, str) or name_re.fullmatch(ident) is None:
                issues.append(
                    _issue(
                        f"{prefix}.id",
                        "tool id must match /^[A-Za-z0-9_.-]{1,128}$/",
                    )
                )
        elif isinstance(name, str) and name_re.fullmatch(name) is None:
            issues.append(
                _issue(
                    prefix,
                    "stable id is required when name is not a tool token (set id)",
                )
            )

        token = _tool_token(tool, index)
        if token in seen:
            issues.append(
                _issue(
                    f"{prefix}.id" if isinstance(tool.get("id"), str) else prefix,
                    f"duplicate tool id {token!r} (also tools[{seen[token]}])",
                )
            )
        else:
            seen[token] = index

        annotations = tool.get("annotations")
        if "annotations" in tool and not isinstance(annotations, dict):
            issues.append(_issue(f"{prefix}.annotations", "annotations must be an object"))
        elif isinstance(annotations, dict):
            for key in sorted(set(annotations) - ALLOWED_ANNOTATIONS):
                issues.append(
                    _issue(
                        f"{prefix}.annotations.{key}",
                        f"unknown annotation key {key!r}",
                    )
                )

        if isinstance(annotations, dict):
            declared = tool.get("consequential")
            hinted = annotations.get("consequentialHint")
            if isinstance(declared, bool) and isinstance(hinted, bool) and declared != hinted:
                issues.append(
                    _issue(f"{prefix}.annotations.consequentialHint", "contradicts consequential")
                )
            if (declared is True or hinted is True) and annotations.get("readOnlyHint") is True:
                issues.append(
                    _issue(
                        f"{prefix}.annotations.readOnlyHint",
                        "consequential tool cannot be read-only",
                    )
                )
        consequential = tool.get("consequential") is True or (
            isinstance(annotations, dict) and annotations.get("consequentialHint") is True
        )
        if consequential and "enabled" not in tool:
            issues.append(
                _issue(
                    prefix,
                    f"consequential tool {token!r} without explicit enable",
                )
            )

    return issues


def _schema_for(allowed_profiles: tuple[str, ...]) -> dict[str, Any]:
    schema = load_schema()
    schema["properties"]["profile"]["enum"] = list(allowed_profiles)
    return schema


def _schema_issues(
    data: Any,
    schema: dict[str, Any],
    semantic_paths: set[str],
) -> list[ValidationIssue]:
    if not isinstance(data, dict):
        return []
    validator = Draft202012Validator(schema)
    issues: list[ValidationIssue] = []
    for error in validator.iter_errors(data):
        if error.validator in _SKIP_SCHEMA_VALIDATORS:
            continue
        formatted = _format_path(error.absolute_path)
        if error.validator == "type" and formatted in semantic_paths:
            continue
        if error.validator == "required":
            # "'enabled' is a required property" — semantic check already says why.
            missing = _required_name(error.message)
            if missing in _SEMANTIC_REQUIRED:
                continue
        if error.validator == "additionalProperties" and _is_annotation_path(error.absolute_path):
            # Semantic check reports "unknown annotation key".
            continue
        if error.validator == "enum" and list(error.absolute_path) == ["profile"]:
            continue
        if error.validator == "type" and list(error.absolute_path) == ["version"]:
            continue
        if error.validator == "type" and list(error.absolute_path) == ["tools"]:
            continue
        if (
            error.validator == "minLength"
            and error.absolute_path
            and error.absolute_path[-1]
            in {
                "name",
                "description",
                "profile",
                "version",
            }
        ):
            continue
        issues.append(_issue(formatted, error.message))
    return issues


def _required_name(message: str) -> str | None:
    # jsonschema: "'enabled' is a required property"
    if message.startswith("'") and "' is a required property" in message:
        return message.split("'", 2)[1]
    return None


def _is_annotation_path(path: Any) -> bool:
    parts = list(path)
    return "annotations" in parts


def _allowed(extra_profiles: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    names = list(builtin_profiles())
    for name in extra_profiles:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("allow-profile values must be non-empty strings")
        if name not in names:
            names.append(name)
    return tuple(names)


def validate_data(
    data: Any,
    *,
    source: str = "<memory>",
    extra_profiles: tuple[str, ...] | list[str] = (),
) -> ValidationResult:
    """Validate a parsed manifest. Does not read the filesystem or import Django."""
    allowed = _allowed(extra_profiles)
    semantic = _semantic_issues(data, allowed)
    schema_issues = _schema_issues(data, _schema_for(allowed), {issue.path for issue in semantic})
    issues = _dedupe([*semantic, *schema_issues])
    return ValidationResult(ok=not issues, source=source, issues=tuple(issues), fatal=False)


def _dedupe(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    seen: set[tuple[str, str]] = set()
    unique: list[ValidationIssue] = []
    for issue in issues:
        key = (issue.path, issue.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def _fatal(source: str, message: str) -> ValidationResult:
    return ValidationResult(
        ok=False,
        source=source,
        issues=(_issue("$", message),),
        fatal=True,
    )


def _load_yaml(text: str) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to validate YAML manifests. "
            "Install pyyaml (Django is not required; see issue #15)."
        ) from exc
    return yaml.safe_load(text)


def load_manifest(path: Path | str) -> tuple[Any, ValidationResult | None]:
    """Read a JSON or YAML manifest without validating it.

    Returns ``(data, None)`` when the file parses, or ``(None, fatal)`` when
    it is missing, empty, or the wrong type. Does not import Django.
    """
    source = Path(path)
    display = str(source)
    if source.suffix.lower() not in _JSON_SUFFIXES | _YAML_SUFFIXES:
        return None, _fatal(display, "unsupported manifest type; use .json, .yaml, or .yml")
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeError:
        return None, _fatal(display, "manifest must be UTF-8")
    except OSError as exc:
        return None, _fatal(display, f"cannot read manifest: {exc.strerror or exc}")
    if not text.strip():
        return None, _fatal(display, "manifest file is empty")
    try:
        if source.suffix.lower() in _YAML_SUFFIXES:
            data = _load_yaml(text)
        else:
            data = json.loads(text)
    except RuntimeError as exc:
        return None, _fatal(display, str(exc))
    except json.JSONDecodeError as exc:
        return None, _fatal(display, f"invalid JSON: {exc.msg} (line {exc.lineno})")
    except Exception as exc:
        # PyYAML raises yaml.YAMLError, which we must not require at import time.
        name = type(exc).__name__
        if name == "YAMLError" or type(exc).__module__.startswith("yaml"):
            return None, _fatal(display, f"invalid YAML: {exc}")
        raise
    if data is None:
        return None, _fatal(display, "manifest file is empty")
    return data, None


def validate_path(
    path: Path | str,
    *,
    extra_profiles: tuple[str, ...] | list[str] = (),
) -> ValidationResult:
    """Load ``path`` as JSON or YAML and validate it."""
    data, fatal = load_manifest(path)
    if fatal is not None:
        return fatal
    return validate_data(data, source=str(Path(path)), extra_profiles=extra_profiles)


def exit_code(results: list[ValidationResult]) -> int:
    """Return 0 when every manifest is valid, 2 on I/O or parse failure, else 1."""
    if any(result.fatal for result in results):
        return 2
    if any(not result.ok for result in results):
        return 1
    return 0


def render_text(results: list[ValidationResult]) -> str:
    """Human-readable report. One block per file, lifecycle note included."""
    blocks: list[str] = []
    for result in results:
        if result.fatal:
            header = f"error: {result.source}"
        elif result.ok:
            header = f"ok: {result.source}"
        else:
            header = f"invalid: {result.source}"
        lines = [header]
        for issue in result.issues:
            lines.append(f"- {issue.path}: {issue.message}")
        for note in result.notes:
            lines.append(f"note: {note}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def render_json(results: list[ValidationResult]) -> str:
    """Machine-readable report (one JSON document)."""
    payload: Any
    if len(results) == 1:
        payload = results[0].to_dict()
    else:
        payload = [result.to_dict() for result in results]
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render(results: list[ValidationResult], fmt: str) -> str:
    """Render results as ``text`` or ``json``."""
    if fmt == "json":
        return render_json(results)
    if fmt == "text":
        return render_text(results)
    raise ValueError(f"unknown format {fmt!r}")


def main(argv: list[str] | None = None) -> int:
    """Entry for ``python -m ais_webmcp.validate`` (no Django import)."""
    import sys

    from ais_webmcp.cli import main as cli_main

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "validate":
        args = ["validate", *args]
    return cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
