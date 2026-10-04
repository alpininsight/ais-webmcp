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
    LIFECYCLE_NOTE,
    builtin_profiles,
    load_schema,
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
    "unknown-annotation.json": "unknown annotation key 'debugging'",
    "ambiguous-schema-keys.json": "ambiguous schema keys",
    "unknown-profile.json": "unknown profile",
    "input-schema-not-object.json": "must be a JSON object",
    "missing-name.json": "missing name",
    "missing-description.json": "missing description",
}


def _webpage() -> dict:
    return json.loads(VALID_JSON.read_text(encoding="utf-8"))


def _run_module(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "packages" / "ais-webmcp" / "src"),
            str(REPO_ROOT / "packages" / "insight-ui-webmcp" / "src"),
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
    assert "debugging" not in schema["$defs"]["annotations"]["properties"]


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
        assert result.notes == (LIFECYCLE_NOTE,)


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


@pytest.mark.unit
def test_validate_module_entry_accepts_a_file() -> None:
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "packages" / "ais-webmcp" / "src"),
            str(REPO_ROOT / "packages" / "insight-ui-webmcp" / "src"),
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
            str(REPO_ROOT / "packages" / "ais-webmcp" / "src"),
            str(REPO_ROOT / "packages" / "insight-ui-webmcp" / "src"),
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
            str(REPO_ROOT / "packages" / "ais-webmcp" / "src"),
            str(REPO_ROOT / "packages" / "insight-ui-webmcp" / "src"),
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
