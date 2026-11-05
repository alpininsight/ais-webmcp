"""Schema and Django-free manifest validation (issue #20 P0)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from webmcp_manifest.profiles import list_profiles
from webmcp_manifest.profiles.webpage import WebpageProfile
from webmcp_manifest.validate import (
    HINTS_NOT_SAFE_CODE,
    HINTS_NOT_SAFE_MESSAGE,
    HINTS_NOT_SAFE_SEVERITY,
    HINTS_NOTE,
    INVISIBLE_OR_CONTROL_MESSAGE,
    LIFECYCLE_NOTE,
    MISSING_OUTPUT_SCHEMA_CODE,
    MISSING_OUTPUT_SCHEMA_MESSAGE,
    MISSING_OUTPUT_SCHEMA_SEVERITY,
    OVERSIZED_SCHEMA_FIELD_CODE,
    OVERSIZED_SCHEMA_FIELD_SEVERITY,
    SCHEMA_DESCRIPTION_SOFT_MAX,
    SCHEMA_PROPERTY_NAME_MAX,
    TOOL_DESCRIPTION_SOFT_MAX,
    ValidationResult,
    builtin_profiles,
    exit_code,
    load_schema,
    render_text,
    schema_path,
    validate_data,
    validate_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_JSON = REPO_ROOT / "tests" / "fixtures" / "manifests" / "valid" / "webpage.json"
VALID_YAML = REPO_ROOT / "tests" / "fixtures" / "manifests" / "valid" / "webpage.yaml"
INVALID = REPO_ROOT / "tests" / "fixtures" / "manifests" / "invalid"
GATE = REPO_ROOT / "tests" / "check_validate_fixtures.py"

EXPECTED = {
    "duplicate-id.json": "duplicate tool id",
    "consequential-without-enable.json": "without explicit enable",
    "missing-input-schema.json": "missing inputSchema",
    "unknown-annotation.json": "unknown annotation key 'notARealHint'",
    "ambiguous-schema-keys.json": "ambiguous schema keys",
    "unknown-profile.json": "unknown profile",
    "input-schema-not-object.json": "must be a JSON object",
    "missing-name.json": "missing name",
    "missing-description.json": "missing description",
    "output-schema-not-object.json": "outputSchema must be a JSON object",
    "invalid-output-schema.json": "invalid Draft 2020-12 output schema",
    "ambiguous-output-schema-keys.json": "ambiguous output schema keys",
}


def _webpage() -> dict:
    return json.loads(VALID_JSON.read_text(encoding="utf-8"))


def _run_module(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "src"),
        ]
    )
    return subprocess.run(
        [sys.executable, "-m", "ais_webmcp", *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_schema_file_is_draft_2020_12() -> None:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "urn:insight-ui-webmcp:webmcp-manifest:1"
    assert schema_path().is_file()
    assert "debugging" in schema["$defs"]["annotations"]["properties"]
    tool = schema["$defs"]["tool"]["properties"]
    assert tool["outputSchema"]["$ref"] == "#/$defs/outputSchema"
    assert tool["output_schema"]["$ref"] == "#/$defs/outputSchema"
    assert schema["$defs"]["outputSchema"]["type"] == "object"


@pytest.mark.unit
def test_builtin_profiles_match_registry() -> None:
    """Schema enum is the profile SSOT and must not drift from the registry."""
    assert set(builtin_profiles()) == set(list_profiles())
    assert "webpage" in builtin_profiles()


@pytest.mark.unit
def test_valid_fixture_matches_prepare_manifest_and_stays_default_off() -> None:
    payload = WebpageProfile().build_manifest(version="1").to_dict()
    on_disk = _webpage()
    assert on_disk == payload
    as_yaml = yaml.safe_load(VALID_YAML.read_text(encoding="utf-8"))
    assert as_yaml == on_disk
    subscribe = next(tool for tool in on_disk["tools"] if tool["id"] == "subscribe_newsletter")
    assert subscribe["consequential"] is True
    assert subscribe["enabled"] is False
    assert subscribe["annotations"]["consequentialHint"] is True
    assert not any(
        str(tool.get("id", "")).startswith("subscribe_") and tool.get("enabled") is True
        for tool in on_disk["tools"]
    )


@pytest.mark.unit
def test_validate_accepts_json_and_yaml_fixtures() -> None:
    for path in (VALID_JSON, VALID_YAML):
        result = validate_path(path)
        assert result.ok, result.issues
        assert result.fatal is False
        assert result.notes == (LIFECYCLE_NOTE, HINTS_NOTE)


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_invalid_fixtures(name: str) -> None:
    result = validate_path(INVALID / name)
    assert result.ok is False
    assert result.fatal is False
    blob = " ".join(issue.message for issue in result.issues)
    assert EXPECTED[name] in blob
    assert LIFECYCLE_NOTE in result.notes


@pytest.mark.unit
def test_schema_key_aliases_and_explicit_opt_in() -> None:
    base = _webpage()
    tool = dict(base["tools"][0])
    tool.pop("inputSchema")
    tool["parameters"] = {"type": "object", "properties": {}}
    assert validate_data({**base, "tools": [tool]}).ok

    tool = dict(base["tools"][0])
    tool.pop("inputSchema")
    tool["input_schema"] = {"type": "object"}
    assert validate_data({**base, "tools": [tool]}).ok

    opted = json.loads(json.dumps(base))
    subscribe = next(item for item in opted["tools"] if item["id"] == "subscribe_newsletter")
    subscribe["enabled"] = True
    # Hosts may opt in. The committed webpage fixture must not (asserted above).
    assert validate_data(opted).ok

    both = json.loads(json.dumps(base))
    both["tools"][0]["parameters"] = {"type": "object"}
    ambiguous = validate_data(both)
    assert ambiguous.ok is False
    assert any("ambiguous schema keys" in issue.message for issue in ambiguous.issues)


@pytest.mark.unit
def test_stable_id_required_for_human_name() -> None:
    data = _webpage()
    tool = dict(data["tools"][0])
    tool.pop("id")
    result = validate_data({**data, "tools": [tool]})
    assert result.ok is False
    assert any("stable id" in issue.message for issue in result.issues)

    token = dict(tool)
    token["name"] = "list_sections"
    assert validate_data({**data, "tools": [token]}).ok


@pytest.mark.unit
def test_allow_profile_extends_schema_enum(tmp_path: Path) -> None:
    data = _webpage()
    data["profile"] = "docs"
    assert validate_data(data).ok is False
    assert validate_data(data, extra_profiles=("docs",)).ok
    target = tmp_path / "docs.json"
    target.write_text(json.dumps(data), encoding="utf-8")
    assert validate_path(target, extra_profiles=("docs",)).ok


@pytest.mark.unit
def test_unreadable_manifest_is_fatal(tmp_path: Path) -> None:
    missing = validate_path(tmp_path / "missing.json")
    assert missing.ok is False and missing.fatal is True

    text = tmp_path / "notes.txt"
    text.write_text("{}", encoding="utf-8")
    suffix = validate_path(text)
    assert suffix.fatal is True
    assert "unsupported" in suffix.issues[0].message

    unquoted = tmp_path / "version.yaml"
    unquoted.write_text("profile: webpage\nversion: 1\ntools: []\n", encoding="utf-8")
    parsed = validate_path(unquoted)
    assert parsed.ok is False
    assert any("non-empty string" in issue.message for issue in parsed.issues)


@pytest.mark.unit
def test_cli_exits_match_fixtures() -> None:
    ok = _run_module("validate", str(VALID_JSON), str(VALID_YAML))
    assert ok.returncode == 0, ok.stderr + ok.stdout
    assert "ok:" in ok.stdout
    assert LIFECYCLE_NOTE in ok.stdout
    assert "must not be treated as safe" in ok.stdout

    bad = _run_module("validate", str(INVALID / "duplicate-id.json"))
    assert bad.returncode == 1
    assert "duplicate tool id" in bad.stdout

    missing = _run_module("validate", str(REPO_ROOT / "tests" / "no-such-manifest.json"))
    assert missing.returncode == 2

    as_json = _run_module("validate", "--format", "json", str(VALID_JSON))
    assert as_json.returncode == 0
    payload = json.loads(as_json.stdout)
    assert payload["ok"] is True
    assert LIFECYCLE_NOTE in payload["notes"]
    assert HINTS_NOTE in payload["notes"]


@pytest.mark.unit
def test_validate_module_entry_accepts_a_file() -> None:
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "src"),
        ]
    )
    proc = subprocess.run(
        [sys.executable, "-m", "webmcp_manifest.validate", str(VALID_YAML)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "ok:" in proc.stdout


@pytest.mark.unit
def test_validate_import_does_not_load_django() -> None:
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "src"),
        ]
    )
    code = (
        "import sys\n"
        "import ais_webmcp.cli\n"
        "import webmcp_manifest.validate\n"
        "assert 'django' not in sys.modules\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.unit
def test_fixture_gate_script() -> None:
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "src"),
        ]
    )
    proc = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


@pytest.mark.unit
def test_debugging_annotation_is_allowed_when_explicit() -> None:
    """Host-opted debugging tools validate; production webpage fixture stays clean (#9)."""
    payload = _webpage()
    assert all(not (tool.get("annotations") or {}).get("debugging") for tool in payload["tools"])
    debug_path = REPO_ROOT / "tests" / "fixtures" / "manifests" / "valid" / "debugging-opt-in.json"
    result = validate_path(debug_path)
    assert result.ok, result.issues
    data = json.loads(debug_path.read_text(encoding="utf-8"))
    assert data["tools"][0]["annotations"]["debugging"] is True


@pytest.mark.unit
def test_toolspec_never_emits_debugging_without_opt_in() -> None:
    from webmcp_manifest.manifest import ToolSpec

    tool = ToolSpec(
        id="inspect_dom_snapshot",
        name="Inspect",
        description="Dev only",
        read_only=True,
        debugging=True,
    )
    plain = tool.to_dict()
    assert "debugging" not in plain["annotations"]
    opted = tool.to_dict(include_debugging=True)
    assert opted["annotations"]["debugging"] is True


def _one_tool() -> dict:
    data = _webpage()
    data["tools"] = [dict(data["tools"][0])]
    return data


@pytest.mark.unit
def test_output_schema_present_missing_and_invalid() -> None:
    """Present schemas pass, missing ones are low findings, invalid ones fail."""
    present = _one_tool()
    present["tools"][0]["outputSchema"] = {
        "type": "object",
        "properties": {"sections": {"type": "array", "items": {"type": "string"}}},
    }
    present_result = validate_data(present)
    assert present_result.ok, present_result.issues
    assert present_result.findings == ()

    alias = _one_tool()
    alias["tools"][0]["output_schema"] = {"type": "string"}
    alias_result = validate_data(alias)
    assert alias_result.ok, alias_result.issues
    assert alias_result.findings == ()

    empty = _one_tool()
    empty["tools"][0]["outputSchema"] = {}
    empty_result = validate_data(empty)
    assert empty_result.ok, empty_result.issues
    assert empty_result.findings == ()

    missing = validate_data(_one_tool())
    assert missing.ok, missing.issues
    assert len(missing.findings) == 1
    finding = missing.findings[0]
    assert finding.path == "tools[0]"
    assert finding.code == MISSING_OUTPUT_SCHEMA_CODE
    assert finding.severity == MISSING_OUTPUT_SCHEMA_SEVERITY
    assert finding.message == MISSING_OUTPUT_SCHEMA_MESSAGE
    assert missing.to_dict()["findings"] == [
        {
            "path": "tools[0]",
            "code": MISSING_OUTPUT_SCHEMA_CODE,
            "severity": MISSING_OUTPUT_SCHEMA_SEVERITY,
            "message": MISSING_OUTPUT_SCHEMA_MESSAGE,
        }
    ]

    webpage = validate_path(VALID_JSON)
    assert webpage.ok, webpage.issues
    assert len(webpage.findings) == len(_webpage()["tools"])
    assert {item.code for item in webpage.findings} == {MISSING_OUTPUT_SCHEMA_CODE}
    assert {item.severity for item in webpage.findings} == {MISSING_OUTPUT_SCHEMA_SEVERITY}

    shaped = _one_tool()
    shaped["tools"][0]["outputSchema"] = ["not", "an", "object"]
    shape_result = validate_data(shaped)
    assert shape_result.ok is False
    assert shape_result.findings == ()
    assert any(
        issue.path == "tools[0].outputSchema" and "must be a JSON object" in issue.message
        for issue in shape_result.issues
    )

    invalid = _one_tool()
    invalid["tools"][0]["outputSchema"] = {"type": "object", "required": "not-an-array"}
    invalid_result = validate_data(invalid)
    assert invalid_result.ok is False
    assert invalid_result.findings == ()
    assert any(
        "invalid Draft 2020-12 output schema" in issue.message for issue in invalid_result.issues
    )

    both = _one_tool()
    both["tools"][0]["outputSchema"] = {"type": "object"}
    both["tools"][0]["output_schema"] = {"type": "string"}
    ambiguous = validate_data(both)
    assert ambiguous.ok is False
    assert any("ambiguous output schema keys" in issue.message for issue in ambiguous.issues)
    assert ambiguous.findings == ()

    mixed = _webpage()
    mixed["tools"] = [dict(mixed["tools"][0]), dict(mixed["tools"][1])]
    mixed["tools"][1]["outputSchema"] = {"type": "object", "properties": {}}
    mixed_result = validate_data(mixed)
    assert mixed_result.ok, mixed_result.issues
    assert [item.path for item in mixed_result.findings] == ["tools[0]"]

    bare = _one_tool()
    bare["tools"][0].pop("inputSchema")
    bare_result = validate_data(bare)
    assert bare_result.ok is False
    assert any("missing inputSchema" in issue.message for issue in bare_result.issues)
    assert [item.code for item in bare_result.findings] == [MISSING_OUTPUT_SCHEMA_CODE]


@pytest.mark.unit
def test_missing_output_schema_stays_exit_zero(tmp_path: Path) -> None:
    path = tmp_path / "missing-output.json"
    path.write_text(json.dumps(_one_tool()), encoding="utf-8")
    as_json = _run_module("validate", "--format", "json", str(path))
    assert as_json.returncode == 0, as_json.stderr + as_json.stdout
    payload = json.loads(as_json.stdout)
    assert payload["ok"] is True
    assert payload["findings"][0]["code"] == MISSING_OUTPUT_SCHEMA_CODE
    assert payload["findings"][0]["severity"] == "low"

    text = _run_module("validate", str(path))
    assert text.returncode == 0, text.stderr + text.stdout
    assert text.stdout.startswith("ok:")
    assert "finding: tools[0]: [low] missing_output_schema:" in text.stdout

    invalid = _run_module("validate", str(INVALID / "invalid-output-schema.json"))
    assert invalid.returncode == 1
    assert "invalid Draft 2020-12 output schema" in invalid.stdout


@pytest.mark.unit
def test_validation_result_positional_fatal_stays_fatal() -> None:
    """findings is appended after fatal, so historical positional calls stay exit 2."""
    result = ValidationResult(False, "missing.json", (), (LIFECYCLE_NOTE,), True)
    assert result.fatal is True
    assert result.findings == ()
    assert result.ok is False
    assert exit_code([result]) == 2
    payload = result.to_dict()
    assert payload["fatal"] is True
    assert payload["findings"] == []
    text = render_text([result])
    assert text.startswith("error: missing.json")
    assert "finding:" not in text


def test_canonical_manifest_renames_output_schema_alias(tmp_path: Path) -> None:
    from ais_webmcp.operations import canonical_manifest

    data = _one_tool()
    data["tools"][0]["output_schema"] = {"type": "object", "properties": {}}
    path = tmp_path / "alias.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    canonical, result = canonical_manifest(path)
    assert result.ok, result.issues
    assert result.findings == ()
    assert "output_schema" not in canonical["tools"][0]
    assert canonical["tools"][0]["outputSchema"] == {"type": "object", "properties": {}}


def _probe(**overrides: object) -> dict:
    tool: dict = {
        "id": "probe",
        "name": "Probe",
        "description": "Contract probe",
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True},
    }
    tool.update(overrides)
    return {"profile": "webpage", "version": "1", "tools": [tool]}


@pytest.mark.unit
def test_invisible_or_control_characters_fail_names_and_descriptions() -> None:
    """Hidden characters are errors. Ordinary text, including accents, stays valid."""
    hidden = {
        "description zero-width": {"description": "Hello\u200bworld"},
        "description bidi": {"description": "Hello\u202eworld"},
        "description tag": {"description": "Hello\U000e0001world"},
        "description missed ignorable": {"description": "Hello\u2065world"},
        "description unassigned format": {"description": "Hello\ufff0world"},
        "name zero-width": {"name": "Probe\u200b"},
        "id control": {"id": "pro\u0007be"},
        "title bidi": {"title": "Probe\u202e"},
    }
    for label, overrides in hidden.items():
        result = validate_data(_probe(**overrides))
        assert result.ok is False, label
        assert any(INVISIBLE_OR_CONTROL_MESSAGE in issue.message for issue in result.issues), label
        assert exit_code([result]) == 1

    plain = validate_data(_probe(description="Liste des cafés et des 工具."))
    assert plain.ok, plain.issues
    combining = validate_data(_probe(description="cafe\u0301"))
    assert combining.ok, combining.issues


@pytest.mark.unit
def test_whitespace_only_description_is_rejected() -> None:
    for description in ("", "   ", "\n\t", "\u00a0"):
        result = validate_data(_probe(description=description))
        assert result.ok is False
        assert any(
            "missing description (empty or whitespace-only)" in issue.message
            for issue in result.issues
        )
        assert exit_code([result]) == 1


@pytest.mark.unit
def test_oversized_schema_fields_are_low_findings() -> None:
    """Soft maxima flag the field and leave the manifest valid."""
    at_limit = _probe(
        description="d" * TOOL_DESCRIPTION_SOFT_MAX,
        inputSchema={
            "type": "object",
            "description": "s" * SCHEMA_DESCRIPTION_SOFT_MAX,
            "properties": {
                "p" * SCHEMA_PROPERTY_NAME_MAX: {
                    "type": "string",
                    "description": "n" * SCHEMA_DESCRIPTION_SOFT_MAX,
                }
            },
        },
    )
    limited = validate_data(at_limit)
    assert limited.ok, limited.issues
    assert limited.findings == ()

    oversized = _probe(
        description="d" * (TOOL_DESCRIPTION_SOFT_MAX + 1),
        inputSchema={
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "properties": {
                        "q" * (SCHEMA_PROPERTY_NAME_MAX + 1): {
                            "type": "string",
                            "description": "n" * (SCHEMA_DESCRIPTION_SOFT_MAX + 1),
                        }
                    },
                }
            },
        },
        outputSchema={
            "type": "object",
            "description": "o" * (SCHEMA_DESCRIPTION_SOFT_MAX + 1),
        },
    )
    result = validate_data(oversized)
    assert result.ok, result.issues
    assert exit_code([result]) == 0
    by_path = {finding.path: finding for finding in result.findings}
    assert set(by_path) == {
        "tools[0].description",
        "tools[0].inputSchema.properties.outer.properties."
        + ("q" * (SCHEMA_PROPERTY_NAME_MAX + 1)),
        "tools[0].inputSchema.properties.outer.properties."
        + ("q" * (SCHEMA_PROPERTY_NAME_MAX + 1))
        + ".description",
        "tools[0].outputSchema.description",
    }
    assert {finding.code for finding in result.findings} == {OVERSIZED_SCHEMA_FIELD_CODE}
    assert {finding.severity for finding in result.findings} == {OVERSIZED_SCHEMA_FIELD_SEVERITY}
    assert "750" in by_path["tools[0].description"].message
    assert "500" in by_path["tools[0].outputSchema.description"].message
    text = render_text([result])
    assert text.startswith("ok:")
    assert f"[low] {OVERSIZED_SCHEMA_FIELD_CODE}:" in text


@pytest.mark.unit
def test_missing_output_schema_stays_a_low_finding() -> None:
    data = _probe()
    data["tools"][0].pop("outputSchema")
    result = validate_data(data)
    assert result.ok, result.issues
    assert exit_code([result]) == 0
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.code == MISSING_OUTPUT_SCHEMA_CODE
    assert finding.severity == MISSING_OUTPUT_SCHEMA_SEVERITY
    assert finding.message == MISSING_OUTPUT_SCHEMA_MESSAGE


@pytest.mark.unit
def test_missing_hints_are_not_treated_as_safe() -> None:
    """A missing readOnlyHint is a low finding. Setting it does not invent the others."""
    omitted = _probe()
    del omitted["tools"][0]["annotations"]
    result = validate_data(omitted)
    assert result.ok, result.issues
    assert exit_code([result]) == 0
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.path == "tools[0]"
    assert finding.code == HINTS_NOT_SAFE_CODE
    assert finding.severity == HINTS_NOT_SAFE_SEVERITY
    assert finding.message == HINTS_NOT_SAFE_MESSAGE
    for hint in ("readOnlyHint", "destructiveHint", "openWorldHint"):
        assert hint in finding.message
    assert "must not be treated as safe" in finding.message
    assert HINTS_NOTE in result.notes
    text = render_text([result])
    assert text.startswith("ok:")
    assert f"[low] {HINTS_NOT_SAFE_CODE}:" in text
    assert "must not be treated as safe" in text

    explicit = validate_data(_probe())
    assert explicit.ok, explicit.issues
    assert explicit.findings == ()
    assert HINTS_NOTE in explicit.notes
    assert "consequentialHint" in HINTS_NOTE
